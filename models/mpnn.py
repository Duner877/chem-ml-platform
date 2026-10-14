"""Message passing neural network for molecular property prediction.

Two interchangeable back-ends are provided:

``TorchMPNN``
    A real PyTorch implementation (edge-conditioned message passing +
    GRU-free sum aggregation + set2set style readout).

``RidgeMPNN``
    A NumPy back-end used when PyTorch is not installed: ridge regression on
    engineered descriptors.  It exposes exactly the same ``fit`` / ``predict``
    / ``encode`` interface so the nodes never need to know which one runs.
"""

from __future__ import annotations

import json
import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from .descriptors import compute_descriptors, descriptor_vector, DESCRIPTOR_KEYS
from .features import (
    ATOM_FEATURE_DIM,
    BOND_FEATURE_DIM,
    atom_features,
    bond_features,
    graph_to_arrays,
)
from .smiles import MolecularGraph, parse_smiles

try:  # pragma: no cover - depends on the environment
    import torch
    import torch.nn as nn

    HAS_TORCH = True
except ImportError:  # pragma: no cover
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    HAS_TORCH = False


__all__ = [
    "HAS_TORCH",
    "MPNNConfig",
    "TorchMPNN",
    "RidgeMPNN",
    "create_model",
    "train_model",
    "evaluate_model",
    "load_molecule",
]


@dataclass
class MPNNConfig:
    """Hyper-parameters of the message passing model."""

    hidden: int = 128
    depth: int = 3
    dropout: float = 0.0
    readout: str = "mean"
    learning_rate: float = 1e-3
    weight_decay: float = 0.0
    epochs: int = 60
    batch_size: int = 16
    validation_fraction: float = 0.2
    seed: int = 20240521
    target: str = "target"


# --------------------------------------------------------------------------- #
# PyTorch back-end
# --------------------------------------------------------------------------- #
if HAS_TORCH:

    class _MessageLayer(nn.Module):
        """Edge conditioned message construction (Gilmer et al., 2017)."""

        def __init__(self, hidden: int, bond_dim: int):
            super().__init__()
            self.edge_network = nn.Sequential(
                nn.Linear(bond_dim, hidden), nn.ReLU(), nn.Linear(hidden, hidden * hidden)
            )
            self.gru = nn.GRUCell(hidden, hidden)

        def forward(
            self,
            node_state: "torch.Tensor",
            source: "torch.Tensor",
            target: "torch.Tensor",
            bond_features: "torch.Tensor",
        ) -> "torch.Tensor":
            messages = self.edge_network(bond_features).view(-1, self.gru.hidden_size, self.gru.hidden_size)
            incoming = (messages @ node_state[source].unsqueeze(-1)).squeeze(-1)
            aggregated = torch.zeros_like(node_state).index_add_(0, target, incoming)
            return self.gru(aggregated, node_state)

    class TorchMPNN(nn.Module):
        """Graph encoder + property regression head."""

        def __init__(self, config: MPNNConfig):
            super().__init__()
            self.config = config
            self.training_metrics: Dict[str, Any] = {}
            self.atom_encoder = nn.Linear(ATOM_FEATURE_DIM, config.hidden)
            self.layers = nn.ModuleList(
                [_MessageLayer(config.hidden, BOND_FEATURE_DIM) for _ in range(config.depth)]
            )
            self.dropout = nn.Dropout(config.dropout)
            self.readout = nn.Sequential(
                nn.Linear(config.hidden, config.hidden),
                nn.ReLU(),
                nn.Linear(config.hidden, 1),
            )

        def encode(
            self,
            atom_features_matrix: np.ndarray,
            bond_features_matrix: np.ndarray,
            edge_index: np.ndarray,
        ) -> np.ndarray:
            """Return the graph level embedding (NumPy out)."""
            self.eval()
            if atom_features_matrix.shape[0] == 0:
                return np.zeros(self.config.hidden, dtype=np.float32)
            node_state = torch.relu(
                self.atom_encoder(torch.as_tensor(atom_features_matrix, dtype=torch.float32))
            )
            source = torch.as_tensor(edge_index[0], dtype=torch.long)
            target = torch.as_tensor(edge_index[1], dtype=torch.long)
            bonds = torch.as_tensor(bond_features_matrix, dtype=torch.float32)
            with torch.no_grad():
                for layer in self.layers:
                    node_state = layer(node_state, source, target, bonds)
            if self.config.readout == "max":
                embedding = node_state.max(dim=0).values
            else:
                embedding = node_state.mean(dim=0)
            return embedding.detach().cpu().numpy().astype(np.float32)

        def forward(
            self,
            atom_features_matrix: np.ndarray,
            bond_features_matrix: np.ndarray,
            edge_index: np.ndarray,
        ):
            node_state = torch.relu(
                self.atom_encoder(torch.as_tensor(atom_features_matrix, dtype=torch.float32))
            )
            if node_state.shape[0] == 0:
                return self.readout(torch.zeros(self.config.hidden, dtype=torch.float32)).view(1)
            source = torch.as_tensor(edge_index[0], dtype=torch.long)
            target = torch.as_tensor(edge_index[1], dtype=torch.long)
            bonds = torch.as_tensor(bond_features_matrix, dtype=torch.float32)
            for layer in self.layers:
                node_state = layer(node_state, source, target, bonds)
            if self.config.readout == "max":
                embedding = node_state.max(dim=0).values
            else:
                embedding = node_state.mean(dim=0)
            return self.readout(self.dropout(embedding)).view(1)

        def predict(self, smiles: str) -> float:
            """Property prediction for a single SMILES string."""
            atoms, bonds, edges, _ = graph_to_arrays(parse_smiles(smiles))
            with torch.no_grad():
                value = self.forward(atoms, bonds, edges)
            return float(value.item())

        def save(self, path: str | Path) -> Path:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            torch.save(
                {"config": self.config.__dict__, "state": self.state_dict()}, str(path)
            )
            return path

        @classmethod
        def load(cls, path: str | Path) -> "TorchMPNN":
            payload = torch.load(str(path), map_location="cpu")
            model = cls(MPNNConfig(**payload["config"]))
            model.load_state_dict(payload["state"])
            return model

else:  # pragma: no cover - exercised when torch is missing

    class TorchMPNN:  # type: ignore[no-redef]
        """Placeholder raised when PyTorch is not installed."""

        def __init__(self, *args: Any, **kwargs: Any):
            raise NotImplementedError(
                "PyTorch is not installed. Install it (`pip install torch`) or use "
                "the NumPy back-end (`RidgeMPNN`)."
            )


# --------------------------------------------------------------------------- #
# NumPy back-end
# --------------------------------------------------------------------------- #
class RidgeMPNN:
    """Ridge regression on molecular descriptors (NumPy only).

    The interface mirrors :class:`TorchMPNN`:
    ``fit(smiles_list, targets)``, ``predict(smiles)``, ``encode(smiles)``,
    ``save(path)`` / ``load(path)``.
    """

    def __init__(self, config: MPNNConfig | None = None, alpha: float = 1e-2):
        self.config = config or MPNNConfig()
        self.alpha = float(alpha)
        self.keys: List[str] = list(DESCRIPTOR_KEYS)
        self.mean: np.ndarray | None = None
        self.scale: np.ndarray | None = None
        self.weights: np.ndarray | None = None
        self.bias: float = 0.0
        self.training_metrics: Dict[str, float] = {}

    # -- feature engineering ------------------------------------------------ #
    def _features(self, smiles: str) -> np.ndarray:
        descriptors = compute_descriptors(smiles)
        vector = [
            float(descriptors.get(key, 0.0) or 0.0) for key in self.keys
        ]
        # a couple of non linear expansions keep the model expressive
        molwt = float(descriptors.get("MolWt", 0.0) or 0.0)
        logp = float(descriptors.get("MolLogP", 0.0) or 0.0)
        tpsa = float(descriptors.get("TPSA", 0.0) or 0.0)
        vector.extend(
            [
                math.log1p(abs(molwt)),
                logp * logp,
                math.sqrt(max(0.0, tpsa)),
                float(descriptors.get("NumRings", 0) or 0) ** 2,
            ]
        )
        return np.asarray(vector, dtype=np.float64)

    def _matrix(self, smiles_list: Sequence[str]) -> np.ndarray:
        return np.vstack([self._features(item) for item in smiles_list])

    # -- api ------------------------------------------------------------------ #
    def fit(
        self,
        smiles_list: Sequence[str],
        targets: Sequence[float],
        epochs: int | None = None,
        verbose: bool = False,
    ) -> "RidgeMPNN":
        """Fit the ridge model (``epochs`` is accepted for API parity)."""
        rng = np.random.default_rng(self.config.seed)
        features = self._matrix(list(smiles_list))
        y = np.asarray(list(targets), dtype=np.float64)

        indices = np.arange(features.shape[0])
        rng.shuffle(indices)
        n_valid = max(1, int(len(indices) * self.config.validation_fraction))
        valid_idx, train_idx = indices[:n_valid], indices[n_valid:]

        self.mean = features[train_idx].mean(axis=0)
        self.scale = features[train_idx].std(axis=0)
        self.scale[self.scale < 1e-8] = 1.0

        x_train = (features[train_idx] - self.mean) / self.scale
        x_valid = (features[valid_idx] - self.mean) / self.scale

        identity = np.eye(x_train.shape[1])
        gram = x_train.T @ x_train + self.alpha * len(x_train) * identity
        self.weights = np.linalg.solve(gram, x_train.T @ y[train_idx])
        self.bias = float(y[train_idx].mean())

        train_pred = x_train @ self.weights + self.bias
        valid_pred = x_valid @ self.weights + self.bias
        self.training_metrics = {
            "train_rmse": float(np.sqrt(np.mean((train_pred - y[train_idx]) ** 2))),
            "valid_rmse": float(np.sqrt(np.mean((valid_pred - y[valid_idx]) ** 2))),
            "train_r2": _r2(y[train_idx], train_pred),
            "valid_r2": _r2(y[valid_idx], valid_pred),
            "n_train": int(len(train_idx)),
            "n_valid": int(len(valid_idx)),
        }
        if verbose:
            print(self.training_metrics)
        return self

    def predict(self, smiles: str) -> float:
        if self.weights is None or self.mean is None or self.scale is None:
            raise RuntimeError("Model is not fitted -- call fit() first.")
        features = self._features(smiles)
        features = (features - self.mean) / self.scale
        return float(features @ self.weights + self.bias)

    def predict_many(self, smiles_list: Sequence[str]) -> List[float]:
        return [self.predict(item) for item in smiles_list]

    def encode(self, smiles: str) -> np.ndarray:
        """Return a dense embedding: descriptors + a hashed fingerprint part."""
        from .fingerprints import morgan_bits

        descriptors = self._features(smiles)
        bits = sorted(morgan_bits(smiles, radius=2, n_bits=256))
        fingerprint = np.zeros(256, dtype=np.float64)
        for bit in bits:
            fingerprint[bit] = 1.0
        return np.concatenate([descriptors, fingerprint]).astype(np.float32)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(
                {
                    "config": self.config.__dict__,
                    "keys": self.keys,
                    "mean": self.mean,
                    "scale": self.scale,
                    "weights": self.weights,
                    "bias": self.bias,
                    "metrics": self.training_metrics,
                    "alpha": self.alpha,
                },
                handle,
            )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "RidgeMPNN":
        with Path(path).open("rb") as handle:
            payload = pickle.load(handle)
        model = cls(MPNNConfig(**payload["config"]), alpha=payload["alpha"])
        model.keys = payload["keys"]
        model.mean = payload["mean"]
        model.scale = payload["scale"]
        model.weights = payload["weights"]
        model.bias = payload["bias"]
        model.training_metrics = payload.get("metrics", {})
        return model

    def metrics(self) -> Dict[str, float]:
        """Return the metrics recorded during the last :meth:`fit`."""
        return dict(self.training_metrics)


# --------------------------------------------------------------------------- #
# Factory helpers
# --------------------------------------------------------------------------- #
def create_model(config: MPNNConfig | None = None, backend: str = "auto") -> Any:
    """Create a model instance for the requested back-end.

    ``backend`` is one of ``"auto"`` (torch when available), ``"torch"`` or
    ``"numpy"``.
    """
    config = config or MPNNConfig()
    if backend == "torch" and not HAS_TORCH:
        raise NotImplementedError("PyTorch is not installed.")
    if backend in {"auto", "torch"} and HAS_TORCH:
        torch.manual_seed(config.seed)
        return TorchMPNN(config)
    return RidgeMPNN(config)


def load_molecule(smiles: str) -> MolecularGraph:
    """Parse ``smiles`` and attach RDKit-free coordinates (2-D layout)."""

    graph = parse_smiles(smiles)
    if not graph.atoms:
        return graph
    coords = _layout_2d(graph)
    for atom, position in zip(graph.atoms, coords):
        atom["coords"] = [float(position[0]), float(position[1]), 0.0]
    return graph


def _layout_2d(graph: MolecularGraph, iterations: int = 120) -> np.ndarray:
    """Very small force directed layout used for 2-D depictions."""
    rng = np.random.default_rng(7)
    positions = rng.normal(scale=1.0, size=(graph.num_atoms, 2))
    adjacency = graph.adjacency()
    for step in range(iterations):
        forces = np.zeros_like(positions)
        for index, neighbours in adjacency.items():
            for neighbour, order in neighbours:
                delta = positions[index] - positions[neighbour]
                distance = max(1e-6, float(np.linalg.norm(delta)))
                target = 1.35 / float(order)
                forces[index] += (target - distance) * (delta / distance) * 0.5
        for index in range(graph.num_atoms):
            for other in range(index + 1, graph.num_atoms):
                delta = positions[index] - positions[other]
                distance = max(1e-6, float(np.linalg.norm(delta)))
                if distance < 3.0:
                    repulsion = 0.35 / (distance**2)
                    forces[index] += (delta / distance) * repulsion
                    forces[other] -= (delta / distance) * repulsion
        positions += np.clip(forces, -0.5, 0.5) * (1.0 - step / float(iterations))
    return positions


def _r2(observed: np.ndarray, predicted: np.ndarray) -> float:
    """Coefficient of determination."""
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    residual = float(np.sum((observed - predicted) ** 2))
    spread = float(np.sum((observed - observed.mean()) ** 2))
    if spread <= 0:
        return 0.0
    return round(1.0 - residual / spread, 4)


def train_model(
    smiles_list: Sequence[str],
    targets: Sequence[float],
    config: MPNNConfig | None = None,
    backend: str = "auto",
    verbose: bool = False,
) -> Any:
    """Train a property prediction model.

    With the torch back-end a full mini-batch training loop runs; with the NumPy
    back-end the closed form ridge solution is used.  Both return a fitted model.
    """
    config = config or MPNNConfig()
    model = create_model(config, backend=backend)

    if isinstance(model, RidgeMPNN):
        return model.fit(smiles_list, targets, verbose=verbose)

    # -- torch training loop -------------------------------------------------- #
    torch.manual_seed(config.seed)
    graphs = [graph_to_arrays(parse_smiles(item)) for item in smiles_list]
    y = np.asarray(list(targets), dtype=np.float32)

    indices = np.arange(len(graphs))
    rng = np.random.default_rng(config.seed)
    rng.shuffle(indices)
    n_valid = max(1, int(len(indices) * config.validation_fraction))
    valid_idx, train_idx = indices[:n_valid], indices[n_valid:]

    optimizer = torch.optim.Adam(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    criterion = nn.MSELoss()

    history: List[Dict[str, float]] = []
    for epoch in range(max(1, int(config.epochs))):
        model.train()
        order = list(train_idx)
        rng.shuffle(order)
        total = 0.0
        for start in range(0, len(order), max(1, config.batch_size)):
            batch = order[start : start + max(1, config.batch_size)]
            optimizer.zero_grad()
            losses = []
            for index in batch:
                atoms, bonds, edges, _ = graphs[index]
                prediction = model(
                    torch.as_tensor(atoms, dtype=torch.float32),
                    torch.as_tensor(bonds, dtype=torch.float32),
                    torch.as_tensor(edges, dtype=torch.long),
                )
                losses.append(
                    criterion(prediction, torch.tensor([y[index]], dtype=torch.float32))
                )
            loss = torch.stack(losses).mean()
            loss.backward()
            optimizer.step()
            total += float(loss.item())
        train_loss = total / max(1, len(order))
        valid_loss = float("nan")
        if len(valid_idx):
            model.eval()
            with torch.no_grad():
                errors = []
                for index in valid_idx:
                    atoms, bonds, edges, _ = graphs[index]
                    prediction = model(
                        torch.as_tensor(atoms, dtype=torch.float32),
                        torch.as_tensor(bonds, dtype=torch.float32),
                    torch.as_tensor(edges, dtype=torch.long),
                    )
                    errors.append(float(prediction.item()) - float(y[index]))
                valid_loss = float(np.sqrt(np.mean(np.square(errors))))
        history.append({"epoch": epoch + 1, "train_loss": train_loss, "valid_rmse": valid_loss})
        if verbose and (epoch + 1) % 10 == 0:
            print(history[-1])
    model.training_metrics = {
        "epochs": len(history),
        "final_train_loss": history[-1]["train_loss"] if history else 0.0,
        "final_valid_rmse": history[-1]["valid_rmse"] if history else 0.0,
        "history": history,
    }
    return model


def evaluate_model(model: Any, smiles_list: Sequence[str], targets: Sequence[float]) -> Dict[str, float]:
    """RMSE / MAE / R² of ``model`` on a test set."""
    predictions = np.asarray(
        [float(model.predict(item)) for item in smiles_list], dtype=float
    )
    observed = np.asarray(list(targets), dtype=float)
    residual = predictions - observed
    return {
        "rmse": round(float(np.sqrt(np.mean(residual**2))), 4),
        "mae": round(float(np.mean(np.abs(residual))), 4),
        "r2": _r2(observed, predictions),
        "n": int(len(observed)),
    }

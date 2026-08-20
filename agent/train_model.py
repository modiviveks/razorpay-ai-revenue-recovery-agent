"""Train a small reproducible recovery-propensity model from synthetic outcomes.

This intentionally avoids heavyweight ML dependencies. The output is a versioned
logistic-style model used only for prediction; deterministic policy remains the
financial authority.
"""

import json
import math
import random
from pathlib import Path

from agent.intelligence import MODEL_PATH, MODEL_VERSION, BASE_RECOVERY_PROBABILITY
from models import FailureClass

FEATURES = 6


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x))))


def train(seed: int = 42, samples_per_class: int = 250) -> dict:
    random.seed(seed)
    rows: list[tuple[list[float], int]] = []
    classes = list(BASE_RECOVERY_PROBABILITY)
    for failure_class in classes:
        base = BASE_RECOVERY_PROBABILITY[failure_class]
        for _ in range(samples_per_class):
            alternate = 1.0 if failure_class in (FailureClass.INSUFFICIENT_FUNDS, FailureClass.CARD_EXPIRED) else 0.0
            retry = random.randint(0, 2)
            amount_bucket = random.randint(1, 10) / 10.0
            latent = -0.5 + 3.0 * (base - 0.35) + 0.45 * alternate - 0.65 * (retry / 2) - 0.15 * amount_bucket
            probability = sigmoid(latent)
            outcome = 1 if random.random() < probability else 0
            rows.append(([1.0, base, alternate, 1.0 - alternate, retry / 2.0, amount_bucket], outcome))

    weights = [0.0] * FEATURES
    learning_rate = 0.08
    for _ in range(500):
        gradients = [0.0] * FEATURES
        for features, target in rows:
            prediction = sigmoid(sum(w * x for w, x in zip(weights, features)))
            error = prediction - target
            for i, value in enumerate(features):
                gradients[i] += error * value
        scale = 1.0 / len(rows)
        for i in range(FEATURES):
            weights[i] -= learning_rate * gradients[i] * scale

    payload = {
        "model_version": MODEL_VERSION,
        "feature_version": "features-v1",
        "training_seed": seed,
        "training_samples": len(rows),
        "weights": weights,
    }
    MODEL_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    result = train()
    print(f"Trained {result['model_version']} on {result['training_samples']} synthetic outcomes")
    print(f"Saved {MODEL_PATH}")

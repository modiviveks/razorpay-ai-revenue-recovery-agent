"""Controlled local training command: python -m agent.train_model."""
from agent.recovery_model import RecoveryPropensityModel, synthetic_training_data
if __name__ == "__main__":
    rows, labels = synthetic_training_data()
    print(RecoveryPropensityModel().train(rows, labels))

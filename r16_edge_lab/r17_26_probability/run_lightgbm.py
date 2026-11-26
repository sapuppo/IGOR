"""Reuse existing FreqAI-family LightGBM estimator; no Freqtrade code copied."""
import os
os.environ.setdefault('OMP_NUM_THREADS','4');os.environ.setdefault('OPENBLAS_NUM_THREADS','4')
import json,warnings
from pathlib import Path
import train as trainer
import run as runner
warnings.filterwarnings('ignore',message='X does not have valid feature names')
root=Path(__file__).resolve().parent
extension=json.loads((root/'lightgbm_extension.json').read_text())
trainer.PARAMS=extension['parameters'];trainer.MODEL_DIR='models_lightgbm'
runner.PARAMS=trainer.PARAMS;runner.train_fold=trainer.train_fold;runner.O=root/'results_lightgbm';runner.O.mkdir(exist_ok=True)
if __name__=='__main__':runner.main()

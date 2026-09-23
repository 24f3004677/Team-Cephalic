from app import create_app
from flask import Flask
import os
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["TF_NUM_INTRAOP_THREADS"] = "2"
os.environ["TF_NUM_INTEROP_THREADS"] = "2"
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["CUDA_VISIBLE_DEVICES"] = ""     # force CPU mode for reproducibility

from app import create_app
app = create_app()


if __name__ == '__main__':
	app.run(debug=True)
	
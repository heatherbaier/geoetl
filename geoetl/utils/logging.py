import logging
import os

def setup_logging(log_path=None, level=logging.INFO):
    """Configure a basic console + optional file logger."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(level=level, format=log_format)

    if log_path:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(logging.Formatter(log_format))
        root = logging.getLogger()
        root.addHandler(file_handler)

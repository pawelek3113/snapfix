import logging
from pathlib import Path

class LoggerBuilder:
    @staticmethod
    def build(log_file: Path) -> logging.Logger:
        logger = logging.getLogger("memories_fixer")
        logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] | %(filename)s, %(funcName)s, Ln %(lineno)d : %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger
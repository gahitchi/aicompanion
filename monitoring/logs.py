import logging

logging.basicConfig(
    filename="system.log",
    level=logging.INFO
)


def log(event):

    logging.info(str(event))
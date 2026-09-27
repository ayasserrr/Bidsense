import os

from helpers import get_settings


class BaseController:

    def __init__(self):

        self.app_settings = get_settings()

        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self.files_dir = os.path.join(
            self.base_dir,
            "assets/offers"
        )

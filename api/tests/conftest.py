"""The tests run the application against TimeOffice through the fictional SQL boundary of `inspection_fixture`,
also where `.env` configures the demo station; `test_demo.py` tests the demo station on its own."""

import os

os.environ["DATA_SOURCE"] = "timeoffice"

import sys

from app import bidi

# reportlab reads right-to-left text through a module named rlbidi, which isn't on PyPI: this
# app's own implementation stands in, registered before reportlab's text layer is imported
# (app.bidi, tracker FONT-003). One already installed is used instead.
sys.modules.setdefault("rlbidi", bidi)

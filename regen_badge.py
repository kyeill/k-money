"""Redraw the Pushover notification badge from the app icon.

    python regen_badge.py

Pushover keeps its OWN copy of the icon, so this only updates the files in the
repo. They still have to be uploaded by hand at https://pushover.net/apps --
nothing in this project can do that, and forgetting it is why the badge and the
home screen were a whole icon apart.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location("shell", os.path.join(HERE, "site.py"))
shell = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell)

for size in (72, 192):
    path = os.path.join(HERE, "apps-script", "pushover-icon-%d.png" % size)
    with open(path, "wb") as fh:
        fh.write(shell._png(size))
    print("wrote %s (%d bytes)" % (os.path.basename(path), os.path.getsize(path)))

print("\nNow upload the 72px one at https://pushover.net/apps -- nothing here "
      "does that for you.")

import os
import sys
from pathlib import Path

api_dir = Path(__file__).resolve().parents[1] / "apps" / "api"
os.chdir(api_dir)
sys.path.insert(0, str(api_dir))

from app.seed_demo import main


if __name__ == "__main__":
    main()

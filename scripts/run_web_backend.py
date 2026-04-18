import argparse
import sys
from pathlib import Path

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from web.backend.main import app


def main() -> None:
    parser = argparse.ArgumentParser(description='Run the web backend for this repository.')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == '__main__':
    main()

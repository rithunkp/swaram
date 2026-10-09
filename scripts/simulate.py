import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url: str, method: str = "GET") -> object:
    request = Request(url, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except (HTTPError, URLError) as exc:
        raise SystemExit(f"API request failed: {exc}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a mock campaign simulation")
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--retry", action="store_true")
    parser.add_argument("--n", type=int, help="Expected contact count, useful for the seeded 200-contact demo")
    args = parser.parse_args()
    campaign_url = f"{args.api.rstrip('/')}/campaigns/{args.campaign}"
    detail = request_json(campaign_url)
    count = int(detail["contact_count"])
    if args.n is not None and count != args.n:
        raise SystemExit(f"Campaign contains {count} contacts, expected {args.n}.")
    endpoint = "retry" if args.retry else "launch"
    result = request_json(f"{campaign_url}/{endpoint}", "POST")
    print(f"Mock {endpoint} started for {count} contacts.")
    while True:
        detail = request_json(campaign_url)
        if detail["status"] != "running":
            break
        time.sleep(1)
    summary = detail["summary"]
    print(f"Simulation complete: {summary['completed_calls']} calls. Outcomes: {summary['outcomes']}")
    if endpoint == "retry":
        print(f"Queued: {result.get('queued', 0)}")


if __name__ == "__main__":
    main()

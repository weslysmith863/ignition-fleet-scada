"""Ask every gateway whether it is up and set up the way the repo says (ADR 0005). Read-only: it only asks, it never changes anything.

    python -m generator.status                  # every gateway, then the mock CMMS
    python -m generator.status --only site1     # limit the gateways (repeat for more)

For each gateway it checks that the gateway answers and accepts its API key, that the name it reports is the one this port should
reach, that it lists no problems of its own, and that the projects the repo deploys there are present and enabled (the same table
generator.deploy_all uses). The mock CMMS is asked for /health. The REST API cannot read tag values (Phase 1 finding 17), so this
says the gateways are up and configured, not that the plant is producing; the Perspective pages show that.
Exit code 0 means every check passed, 1 means at least one did not.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

from generator.deploy_all import projects_for
from generator.gateway import GATEWAYS, GatewayError, RestGateway

CMMS_HEALTH_URL = "http://127.0.0.1:8100/health"


def check_name(reported, expected):
    """Problems with the gateway name. After a Docker restart the PC's published ports can come back crossed (finding 71)."""
    if reported == expected:
        return []
    return ["this port answered as %r but should reach %r (the published ports may be crossed)" % (reported, expected)]


def describe(problem):
    """One line for an item of /overview/problems. The item's shape is a guess (the list is empty on a healthy gateway), so this
    falls back to the item itself."""
    if isinstance(problem, dict):
        for key in ("title", "message", "name"):
            if problem.get(key):
                return str(problem[key])
    return str(problem)[:120]


def check_problems(items):
    """A problem for every item the gateway lists on its own overview."""
    return ["the gateway reports a problem: %s" % describe(item) for item in items]


def check_projects(listed, expected):
    """Problems with the projects on one gateway, as a list of sentences; an empty list means all is well.

    listed: what the gateway's /projects/list answered, a list of [name, enabled] pairs, for example
        [["core", True], ["fleet", True], ["test1", False]].
    expected: the names of the projects the repo deploys on this gateway, for example ["core", "fleet"].

    An expected project that is not listed is a problem, and so is one that is listed but not enabled. A project that is listed
    but not expected (such as the scratch project test1) is not a problem, whether or not it is enabled.
    """
    enabled = dict(listed)
    problems = []
    for name in expected:
        if name not in enabled or not enabled[name]:
            problems.append("there is a problem with " + name)
    return problems


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def gateway_checks(name, gateway):
    """Every check on one gateway. Returns [(what was checked, [problems])]; no problems means the check passed."""
    asked = "the gateway answers and accepts the API key"
    try:
        reported = gateway.reported_name()
    except GatewayError as error:
        return [(asked, [str(error)[:200]])]  # nothing else can be asked without an answer
    expected = projects_for(name)
    results = [(asked, []), ("the gateway's name is %s" % name, check_name(reported, name))]
    later = [
        ("the gateway reports no problems of its own", lambda: check_problems(gateway.problems())),
        ("the projects are present and enabled (%s)" % ", ".join(expected), lambda: check_projects(gateway.project_list(), expected)),
    ]
    for what, run_check in later:
        try:
            results.append((what, run_check()))
        except GatewayError as error:
            results.append((what, [str(error)[:200]]))
    return results


def cmms_checks(fetch=fetch_json):
    """The mock CMMS answers /health with status ok (ADR 0019)."""
    asked = "the mock CMMS answers /health"
    try:
        answer = fetch(CMMS_HEALTH_URL)
    except (urllib.error.URLError, OSError, ValueError) as error:
        return [(asked, ["cannot reach %s: %s" % (CMMS_HEALTH_URL, error)])]
    if not isinstance(answer, dict) or answer.get("status") != "ok":
        return [(asked, ["it answered %s" % json.dumps(answer)[:100]])]
    return [(asked, [])]


def status(gateways, fetch=fetch_json):
    """gateways: {name: gateway}. Returns (the lines to print, how many checks failed, how many were run)."""
    lines, failed, total = [], 0, 0
    sections = [(name, gateway_checks(name, gateway)) for name, gateway in gateways.items()]
    sections.append(("cmms", cmms_checks(fetch)))
    for title, results in sections:
        lines.append("== %s ==" % title)
        for what, problems in results:
            lines.append("  %-4s %s" % ("FAIL" if problems else "ok", what))
            lines.extend("       - %s" % problem for problem in problems)
            failed += 1 if problems else 0
            total += 1
    return lines, failed, total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", action="append", default=[], metavar="GATEWAY", help="limit to this gateway (repeat for more)")
    args = parser.parse_args(argv)
    names = [name for name in GATEWAYS if not args.only or name in args.only]
    try:
        gateways = {name: RestGateway(name) for name in names}
    except GatewayError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    lines, failed, total = status(gateways)
    for line in lines:
        print(line)
    print("all %d checks passed" % total if not failed else "%d of %d checks failed" % (failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

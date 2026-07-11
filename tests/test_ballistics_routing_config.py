from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_nginx_ballistics_hostname_redirects_to_calculator_page():
    config = (ROOT / "nginx" / "nginx.conf").read_text()

    assert "server_name ballisticcalc.shanewiseman.co;" in config
    assert "absolute_redirect off;" in config
    assert "return 302 /ballistics;" in config
    assert "proxy_pass http://ballistics:5002/api/ballistics/calculate;" in config


def test_production_compose_routes_ballistics_hostname_to_web():
    config = (ROOT / "compose.prod.yaml").read_text()

    assert "container_name: reload-ballistics" in config
    assert "BALLISTICS_URL: http://ballistics:5002" in config
    assert "traefik.http.routers.reload-ledger-ballistics.rule=Host(`${BALLISTIC_CALC_HOST:-ballisticcalc.shanewiseman.co}`)" in config
    assert "traefik.http.routers.reload-ledger-ballistics.service=reload-ledger" in config


def test_py_ballisticcalc_dependency_is_pinned():
    requirements = (ROOT / "requirements.txt").read_text()

    assert "py-ballisticcalc==2.2.10" in requirements

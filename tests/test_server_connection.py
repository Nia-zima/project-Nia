import os
import pytest
import requests

if not os.getenv("RUN_SERVER_TESTS"):
    pytest.skip("Set RUN_SERVER_TESTS=1 to run server connectivity checks.", allow_module_level=True)


@pytest.mark.server
@pytest.mark.parametrize(
    "name,url",
    [
        ("LM Studio (LLM)", "http://localhost:1234/v1/models"),
        ("AI Buddy Backend", "http://localhost:8000/health"),
    ],
)
def test_connection(name, url):
    response = requests.get(url, timeout=5)
    assert response.status_code in {200, 404, 405}

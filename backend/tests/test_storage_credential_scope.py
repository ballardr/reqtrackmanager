"""
Pins the bundled object storage's least-privilege credential: the backend's S3
identity can use its own bucket and nothing else.

Two layers:
- `test_backend_identity_*` run against the live storage service the test stack
  starts, authenticating exactly as the backend does (`STORAGE_S3_*`). Skipped
  when that service is unreachable (for example host pytest, where the endpoint
  `storage:9000` does not resolve; set `STORAGE_S3_ENDPOINT_URL=http://localhost:9000`).
- `test_*_compose_*` read the compose files and check how the storage service is
  declared. Skipped when the repository root is not visible (the backend
  container mounts only backend/).
"""

import json
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pytest
import yaml
from botocore.client import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from app.config import get_settings

settings = get_settings()
ROOT = Path(__file__).resolve().parents[2]
COMPOSES = [ROOT / "docker-compose.yml", ROOT / "tests" / "container" / "docker-compose.yml"]


def _client(access_key: str, secret_key: str):
    """Builds an S3 client for the configured storage endpoint with the given credential."""
    return boto3.client(
        "s3",
        endpoint_url=settings.storage_s3_endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=settings.storage_s3_region,
        config=Config(signature_version="s3v4", retries={"max_attempts": 1}, connect_timeout=3),
    )


@pytest.fixture(scope="module")
def backend_client():
    """The client the backend itself uses; skips when the scoped storage stack is not running."""
    if settings.storage_backend != "s3":
        pytest.skip("STORAGE_BACKEND is not s3")
    client = _client(settings.storage_s3_access_key, settings.storage_s3_secret_key)
    try:
        client.head_bucket(Bucket=settings.storage_s3_bucket)
    except EndpointConnectionError:
        pytest.skip("object storage endpoint is not reachable from here")
    except ClientError as exc:
        pytest.fail(f"backend identity cannot reach its own bucket: {exc}")
    return client


def _denied(call) -> bool:
    """True when the call is rejected by the storage service's authorisation."""
    try:
        call()
    except ClientError as exc:
        return exc.response["Error"]["Code"] in {"AccessDenied", "403", "InvalidAccessKeyId", "SignatureDoesNotMatch"}
    return False


def test_backend_identity_can_use_its_own_bucket(backend_client):
    """Write, read, list and delete inside the application bucket all work."""
    key = f"_scope_test/{uuid.uuid4()}"
    bucket = settings.storage_s3_bucket
    backend_client.put_object(Bucket=bucket, Key=key, Body=b"scoped")
    assert backend_client.get_object(Bucket=bucket, Key=key)["Body"].read() == b"scoped"
    assert any(o["Key"] == key for o in backend_client.list_objects_v2(Bucket=bucket, Prefix=key)["Contents"])
    backend_client.delete_object(Bucket=bucket, Key=key)


def test_backend_identity_cannot_touch_another_bucket(backend_client):
    """Another bucket (existing or not) is refused for read, write, delete and listing."""
    other = f"{settings.storage_s3_bucket}-other"
    assert _denied(lambda: backend_client.put_object(Bucket=other, Key="x", Body=b"x"))
    assert _denied(lambda: backend_client.get_object(Bucket=other, Key="x"))
    assert _denied(lambda: backend_client.delete_object(Bucket=other, Key="x"))
    assert _denied(lambda: backend_client.list_objects_v2(Bucket=other))


def test_backend_identity_cannot_administer_other_buckets(backend_client):
    """It cannot list buckets or create another one; creating its own (what startup does) is allowed."""
    assert _denied(lambda: backend_client.list_buckets())
    assert _denied(lambda: backend_client.create_bucket(Bucket=f"{uuid.uuid4()}"))
    # Creating its own bucket is permitted (the backend does it when the bucket is missing); the bucket exists, so it is
    # reported as existing rather than denied.
    with pytest.raises(ClientError) as exc:
        backend_client.create_bucket(Bucket=settings.storage_s3_bucket)
    assert exc.value.response["Error"]["Code"] in {"BucketAlreadyExists", "BucketAlreadyOwnedByYou"}


@pytest.mark.parametrize("port", [8888, 9333, 18888, 8080])
def test_unauthenticated_storage_apis_are_not_reachable(backend_client, port):
    """The filer, master and volume APIs carry no authentication, so they must not be open to the backend."""
    host = urlparse(settings.storage_s3_endpoint_url).hostname
    if host in {"localhost", "127.0.0.1", "::1"}:
        pytest.skip("only meaningful from inside the Compose network; localhost ports belong to other services")
    with pytest.raises(OSError), socket.create_connection((host, port), timeout=3):
        pass


def test_wrong_secret_is_refused(backend_client):
    """The application bucket is not reachable with a guessed secret."""
    wrong = _client(settings.storage_s3_access_key, "not-the-secret")
    assert _denied(lambda: wrong.head_bucket(Bucket=settings.storage_s3_bucket))


needs_checkout = pytest.mark.skipif(not COMPOSES[0].is_file(), reason="repository checkout not available")


def _storage(compose_file: Path) -> tuple[dict, str]:
    """Returns the `storage` service and the text of its identity config for a compose file."""
    compose = yaml.safe_load(compose_file.read_text())
    return compose["services"]["storage"], compose["configs"]["storage_identity"]["content"]


@needs_checkout
@pytest.mark.parametrize("compose_file", COMPOSES, ids=["production", "test-stack"])
def test_compose_keeps_everything_but_the_s3_gateway_on_loopback(compose_file):
    """The unauthenticated filer/master APIs bind to loopback; only the S3 gateway listens on every interface."""
    service, _ = _storage(compose_file)
    args = service["command"].split()
    assert "-ip=127.0.0.1" in args
    assert "-ip.bind=127.0.0.1" in args
    assert "-s3.ip.bind=::" in args
    assert "-s3.config=/etc/seaweedfs/s3.json" in args


@needs_checkout
def test_production_compose_publishes_no_storage_port():
    """Only the backend talks to the bundled storage, over the Compose network."""
    service, _ = _storage(COMPOSES[0])
    assert "ports" not in service


@needs_checkout
@pytest.mark.parametrize("compose_file", COMPOSES, ids=["production", "test-stack"])
def test_compose_identity_is_one_bucket_scoped_identity(compose_file):
    """One identity, and every action is limited to the application bucket (no bare Admin/Read/Write/List)."""
    _, content = _storage(compose_file)
    filled = re.sub(r"\$\{[^}]*\}", "x", content.replace("${STORAGE_S3_BUCKET:-reqtrackmanager}", "BUCKET"))
    identities = json.loads(filled)["identities"]
    assert len(identities) == 1
    actions = identities[0]["actions"]
    assert sorted(actions) == ["Admin:BUCKET", "List:BUCKET", "Read:BUCKET", "Write:BUCKET"]


@needs_checkout
def test_production_compose_refuses_an_unset_secret():
    """An unset secret fails Compose rather than giving the storage service an empty one."""
    _, content = _storage(COMPOSES[0])
    assert re.search(r"secretKey\":\"\$\{STORAGE_SECRET_KEY:-\$\{STORAGE_ROOT_PASSWORD:\?", content)
    backend = yaml.safe_load(COMPOSES[0].read_text())["services"]["backend"]["environment"]
    assert ":?" in backend["STORAGE_S3_SECRET_KEY"]
    assert "ROOT" not in backend["STORAGE_S3_ACCESS_KEY"].replace("STORAGE_ROOT_USER", "")

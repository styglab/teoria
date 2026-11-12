"""Synthetic linear-regression workload for real registry/Kubernetes smoke checks."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

import boto3
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException


def checksum(path):
    digest = hashlib.sha256()
    for file in sorted(path.rglob('*')):
        if file.is_file():
            digest.update(file.relative_to(path).as_posix().encode() + b'\0')
            digest.update(file.read_bytes())
    return digest.hexdigest()


def storage():
    return boto3.client('s3', endpoint_url=os.environ['AWS_ENDPOINT_URL_S3'])


def location(uri):
    value = urlsplit(uri)
    assert value.scheme == 's3' and value.netloc and value.path.strip('/')
    return value.netloc, value.path.lstrip('/')


def train():
    # A workload must not receive platform control credentials or a K8s token.
    assert not os.environ.get('TEORIA_ADMIN_API_TOKEN')
    assert not os.environ.get('PREFECT_API_AUTH_STRING')
    assert not Path('/var/run/secrets/kubernetes.io/serviceaccount/token').exists()
    client = MlflowClient(tracking_uri=os.environ['MLFLOW_TRACKING_URI'])
    s3 = storage()
    bucket, key = location(os.environ['TEORIA_INPUT_URI'])
    response = s3.get_object(Bucket=bucket, Key=key)['Body']
    try:
        snapshot = response.read()
    finally:
        response.close()
    assert hashlib.sha256(snapshot).hexdigest() == os.environ['TEORIA_INPUT_SHA256']
    rows = json.loads(snapshot)
    mean_x = sum(row['x'] for row in rows) / len(rows)
    mean_y = sum(row['y'] for row in rows) / len(rows)
    slope = sum((row['x'] - mean_x) * (row['y'] - mean_y) for row in rows) / sum((row['x'] - mean_x)**2 for row in rows)
    offset = json.loads(os.environ.get('TEORIA_TRAINING_PARAMETERS', '{}')).get('offset', 0)
    model = {'slope': slope, 'intercept': mean_y - slope * mean_x + offset}
    name = os.environ['TEORIA_MODEL_NAME']
    experiment = client.get_experiment_by_name('teoria_k3d_validation')
    experiment_id = experiment.experiment_id if experiment else client.create_experiment('teoria_k3d_validation')
    run = client.create_run(experiment_id, tags={'synthetic': 'true', 'teoria.prefect_flow_run_id': os.environ['TEORIA_TRAINING_RUN_ID']})
    run_id = run.info.run_id
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'model'
        path.mkdir()
        (path / 'model.json').write_text(json.dumps(model, sort_keys=True))
        digest = checksum(path)
        client.log_artifacts(run_id, str(path), 'model')
        client.log_param(run_id, 'offset', offset)
        client.log_metric(run_id, 'training_mse', sum((model['slope'] * r['x'] + model['intercept'] - r['y'])**2 for r in rows) / len(rows))
        try:
            client.get_registered_model(name)
        except MlflowException as error:
            if error.error_code != 'RESOURCE_DOES_NOT_EXIST':
                raise
            client.create_registered_model(name)
        source = client.get_run(run_id).info.artifact_uri.rstrip('/') + '/model'
        version = client.create_model_version(name, source, run_id=run_id, tags={'teoria.model_sha256': digest})
    client.set_terminated(run_id)
    result = {'model_name': name, 'model_version': int(version.version), 'model_sha256': digest, 'run_id': run_id}
    bucket, key = location(os.environ['TEORIA_OUTPUT_URI'])
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(result).encode(), ContentType='application/json')
    print(json.dumps(result))


def serve():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import mlflow.artifacts

    with tempfile.TemporaryDirectory() as directory:
        path = Path(mlflow.artifacts.download_artifacts(artifact_uri=os.environ['TEORIA_MODEL_URI'], dst_path=directory))
        assert checksum(path) == os.environ['TEORIA_MODEL_SHA256']
        model = json.loads((path / 'model.json').read_text())
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200 if self.path == '/health' else 404)
                self.end_headers()

            def do_POST(self):
                if self.path != '/predict':
                    self.send_error(404)
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1048576:
                    self.send_error(413)
                    return
                values = json.loads(self.rfile.read(size))['x']
                body = json.dumps({'predictions': [model['slope'] * x + model['intercept'] for x in values],
                                   'model_version': int(os.environ['TEORIA_MODEL_VERSION'])}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        print('Verified model loaded; serving on 8080.', flush=True)
        HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


if __name__ == '__main__':
    {'train': train, 'serve': serve}[sys.argv[1]]()

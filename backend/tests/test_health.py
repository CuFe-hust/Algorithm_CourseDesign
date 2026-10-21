def test_health_and_documentation_exist_without_database():
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        response = client.get('/api/v1/health')
        assert response.status_code == 200
        assert response.json() == {'status': 'ok'}
        assert response.headers['X-Request-ID']
        assert client.get('/openapi.json').status_code == 200


def test_error_contract_for_invalid_login():
    from fastapi.testclient import TestClient
    from app.main import create_app
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/auth/login', json={})
        assert response.status_code == 422
        assert set(response.json()) == {'code', 'message', 'details', 'request_id'}

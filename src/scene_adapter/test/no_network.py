"""Фикстура pytest: любое сетевое соединение из Python в тесте — ошибка."""

import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('обязательные тесты не должны обращаться к сети')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)

"""
Server module for EchoLens desktop assistant.
"""
from server.service import service_instance, EchoLensService
from server.handlers import EchoLensHTTPHandler

__all__ = ["service_instance", "EchoLensService", "EchoLensHTTPHandler"]

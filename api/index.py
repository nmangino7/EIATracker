"""
Vercel serverless handler — wraps the Flask app for deployment.
All routes are proxied through this single function.
"""
import sys
import os

# Add the project root to the path so we can import app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel expects a WSGI-compatible app object
app = app

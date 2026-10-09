"""Worker para despliegues WSGI que no se inician con python app.py."""
from app import alexa_gateway

if __name__ == '__main__':
    alexa_gateway.run()

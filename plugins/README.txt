PLUGINS DO JARVIS

Cada .py nesta pasta pode implementar:

def can_handle(message):
    return message.lower().strip() == "meu comando"

def handle(message, context):
    return "Resposta do plugin"

Depois diga "recarregue plugins" no JARVIS.

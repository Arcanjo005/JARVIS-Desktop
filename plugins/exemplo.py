def can_handle(message):
    return message.lower().strip() == "teste plugin"

def handle(message, context):
    return "Sistema de plugins do JARVIS funcionando."

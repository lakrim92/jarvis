"""Le cerveau de Jarvis : dialogue avec Ollama + boucle d'appel d'outils."""
import json
import logging

import ollama

import config
from tools import TOOLS_SCHEMA, dispatch_tool

log = logging.getLogger("jarvis.brain")

MAX_TOOL_ROUNDS = 5
MAX_HISTORY_MESSAGES = 24  # au-dela, on tronque (hors system prompt)


class JarvisBrain:
    def __init__(self):
        self.client = ollama.Client(host=config.OLLAMA_HOST)
        self.model = config.OLLAMA_MODEL
        self.messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]

    def _trim_history(self):
        if len(self.messages) > MAX_HISTORY_MESSAGES:
            self.messages = [self.messages[0]] + self.messages[-(MAX_HISTORY_MESSAGES - 1):]

    def reset(self):
        self.messages = [{"role": "system", "content": config.SYSTEM_PROMPT}]

    def load_history(self, turns: list) -> None:
        """Reprend la conversation la ou elle s'est arretee (paires (utilisateur, reponse))."""
        for heard, reply in turns:
            self.messages.append({"role": "user", "content": heard})
            self.messages.append({"role": "assistant", "content": reply})
        self._trim_history()

    def ask(self, user_text: str, context: str = "") -> str:
        """Envoie le texte utilisateur, execute les outils demandes, renvoie la reponse finale."""
        self.messages[0] = {"role": "system",
                            "content": config.SYSTEM_PROMPT + ("\n\nContexte actuel :\n" + context if context else "")}
        self.messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            try:
                response = self.client.chat(
                    model=self.model,
                    messages=self.messages,
                    tools=TOOLS_SCHEMA,
                    options={"num_predict": 300, "temperature": 0.4},
                    keep_alive="30m",
                )
            except Exception as exc:
                log.exception("Erreur Ollama")
                return f"Je n'arrive pas a joindre mon moteur de reflexion local : {exc}"

            msg = response.message
            self.messages.append(msg)

            tool_calls = msg.tool_calls
            if not tool_calls:
                self._trim_history()
                return msg.content or ""

            for call in tool_calls:
                name = call.function.name
                raw_args = call.function.arguments
                if isinstance(raw_args, str):
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        args = {}
                else:
                    args = dict(raw_args) if raw_args else {}

                log.info("Appel outil: %s(%s)", name, args)
                result = dispatch_tool(name, args)
                self.messages.append(
                    {"role": "tool", "name": name, "content": json.dumps(result, ensure_ascii=False)}
                )

        self._trim_history()
        return "Desole, j'ai eu du mal a finir cette action, on peut reessayer ?"

"""Apprentissage de Jarvis : memoire, corrections, annulation, retours de l'utilisateur.

Rien ici ne re-entraine le modele : Jarvis se souvient (faits, corrections, habitudes) et adapte ses reponses.
"""
import logging
import random
import re
import time
import unicodedata
from collections import Counter
from typing import Callable, Optional

import clock
from memory import UNDONE, Memory

log = logging.getLogger("jarvis.learning")

PENDING_SECONDS = 90
_SEP = str.maketrans({"'": " ", "’": " ", "-": " ", ",": " ", ";": " "})


def fold(text: str) -> str:
    """Minuscules sans accents, longueur identique au texte d'origine (pour decouper le texte brut)."""
    return "".join(unicodedata.normalize("NFD", c.lower())[0] for c in text).translate(_SEP)


def fold_map(raw: str):
    """(texte replie sans espaces multiples, index de chaque caractere dans `raw`) pour decouper le texte brut."""
    out, idx = [], []
    for i, ch in enumerate(fold(raw)):
        if ch == " " and (not out or out[-1] == " "):
            continue
        out.append(ch)
        idx.append(i)
    return "".join(out), idx


def phrase_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+]+", " ", fold(text))).strip()


def pick(*variants: str) -> str:
    return random.choice(variants)


P_UNDO = re.compile(r"^(annule|annule (ca|cela)|defais (ca|cela)|reviens en arriere|remets (comme|les choses comme) avant)"
                    r"( s il te plait)?$")
P_THANKS = re.compile(r"^(merci|merci beaucoup|bravo|parfait|super|nickel|genial|bien joue|c est bien|c est parfait|top)"
                      r"( jarvis)?$")
P_WRONG = re.compile(r"^(non|pas ca|c est pas ca|ce n est pas ca|c est faux|tu t es trompe|t as mal compris|"
                     r"tu as mal compris|mauvaise chaine|mauvais volume|faux)( jarvis)?$")
P_WRONG_THEN = re.compile(r"^(?:non|pas ca|c est pas ca|ce n est pas ca) +(.+)$")
P_MEANT = re.compile(r"^(?:non )?(?:je voulais dire|j ai dit|je t ai dit|je disais) +(.+)$")
P_REMEMBER = re.compile(r"^(?:souviens toi que|souviens toi|retiens que|retiens|note que|n oublie pas que|n oublie pas) +(.+)$")
P_NAME = re.compile(r"^(?:appelle moi|tu peux m appeler|je m appelle|mon prenom c est|mon prenom est) +(.+)$")
P_FORGET_ALL = re.compile(r"^oublie tout( ce que tu sais)?$")
P_CONFIRM = re.compile(r"^(?:oui )?(?:oublie tout|confirme|je confirme)(?: oublie tout)?$")
P_FORGET_ALIAS = re.compile(r"^(?:oublie|annule|supprime) (?:la|cette) (?:derniere )?correction$")
P_FORGET_FACT = re.compile(r"^oublie (?:que|le fait que) +(.+)$")
P_KNOW = re.compile(r"^(que sais tu de moi|qu est ce que tu sais (de|sur) moi|tu sais quoi sur moi|de quoi te souviens tu|"
                    r"qu est ce que tu as retenu|qu as tu retenu)$")
P_LEARNED = re.compile(r"^(qu as tu appris|quelles corrections.*|qu est ce que tu as appris)$")
P_BILAN = re.compile(r"^(fais (moi )?un bilan|bilan|donne moi un bilan|fais le point)$")
P_FAVORITE = re.compile(r"\bma chaine (preferee|habituelle|favorite)\b|\bla chaine (habituelle|preferee)\b")


class Learner:
    def __init__(self, memory: Memory, dispatch: Callable[[str, dict], dict]):
        self.mem = memory
        self.dispatch = dispatch
        self.turn_actions: list = []
        self.pending: Optional[dict] = None
        self._mark_undone = False
        self.speaker: Optional[str] = None   # voix reconnue pour l'echange en cours
        self.multi_speaker = False

    # ------------------------------------------------------------ hooks
    def on_dispatch(self, name: str, args: dict, result: dict) -> None:
        if name == "tv_control" and args.get("action") == "status":
            return
        keep = {k: result[k] for k in ("name", "channel", "volume", "error") if k in result}
        self.turn_actions.append({"tool": name, "args": dict(args), "ok": bool(result.get("success")), "result": keep})

    def context(self) -> str:
        """Ce que Jarvis sait deja : injecte dans le prompt du modele a chaque demande."""
        now = clock.now()
        parts = [f"Il est {now.hour} h {now.minute:02d}, {clock.JOURS[now.weekday()]}."]
        name = self.mem.name()
        if self.multi_speaker and self.speaker:
            parts.append(f"Tu parles actuellement avec {self.speaker} (voix reconnue).")
        elif name:
            parts.append(f"L'utilisateur s'appelle {name} : utilise son prenom de temps en temps, naturellement.")
        facts = [f["text"] for f in self.mem.facts() if f["key"] != "name"]
        if facts:
            parts.append("Ce que tu sais sur lui : " + " ; ".join(facts[-12:]) + ".")
        top = self._top_channels(3)
        if top:
            parts.append("Chaines qu'il regarde le plus : " + ", ".join(f"{n} ({c} fois)" for n, c in top) + ".")
        learned = self.mem.aliases()[:3]
        if learned:
            parts.append("Corrections deja apprises : " + " ; ".join(f"« {a['phrase']} » = « {a['target']} »" for a in learned) + ".")
        return "\n".join(parts)

    def greeting(self) -> str:
        """Salutation de reveil, selon l'heure, avec le prenom s'il est connu."""
        hour = clock.now().hour
        evening = hour >= 18 or hour < 5
        hello = "Bonsoir" if evening else "Bonjour"
        when = "ce soir" if evening else "aujourd'hui"
        name = self.speaker if (self.multi_speaker and self.speaker) else self.mem.name()
        who = f" {name}" if name else ""
        return pick(f"{hello}{who} ! Que puis-je faire pour toi {when} ?",
                    f"{hello}{who} ! Qu'est-ce que je peux faire pour toi {when} ?",
                    f"{hello}{who}, comment puis-je t'aider {when} ?")

    # ------------------------------------------------------------ boucle principale
    def respond(self, text: str, pipeline: Callable[[str], tuple]) -> str:
        """pipeline(texte) -> (reponse, 'direct' | 'llm'). Renvoie la reponse a dire."""
        self.turn_actions = []
        original = text
        rewritten = self.mem.get_alias(phrase_key(text))
        if rewritten:
            log.info("Correction apprise appliquee : %r -> %r", text, rewritten)
            text = rewritten

        previous = self._last_real()
        reply = self._meta(text, previous, pipeline)
        by = "meta"
        if reply is None:
            reply, by = pipeline(text)
        interaction_id = self.mem.log_interaction(original, text, by, self.turn_actions, reply)
        self._after_log(interaction_id, by)
        return reply

    def _after_log(self, interaction_id: int, by: str) -> None:
        if self._mark_undone:
            self.mem.set_feedback(interaction_id, UNDONE)   # l'annulation elle-meme ne s'annule pas
            self._mark_undone = False

    def _last_real(self) -> Optional[dict]:
        """L'interaction qui vient d'avoir lieu, si c'est bien une vraie demande, recente et non annulee."""
        rows = self.mem.last_interactions(1, skip_undone=False)
        if not rows:
            return None
        it = rows[0]
        if it["handled_by"] in ("direct", "llm") and it["feedback"] != UNDONE and time.time() - it["ts"] < 180:
            return it
        return None

    # ------------------------------------------------------------ commandes "meta"
    def _meta(self, text: str, prev: Optional[dict], pipeline) -> Optional[str]:
        raw = text.strip().strip(" .!?…,;")
        f, idx = fold_map(raw)

        def span(m, g=1):
            return raw[idx[m.start(g)]:idx[m.end(g) - 1] + 1].strip()

        if self.pending and time.time() > self.pending["until"]:
            self.pending = None

        if P_CONFIRM.match(f) and self.pending and self.pending["kind"] == "forget_all":
            self.mem.forget_everything()
            self.pending = None
            return "C'est fait, j'ai tout oublié. On repart de zéro."
        if P_FORGET_ALL.match(f):
            self.pending = {"kind": "forget_all", "until": time.time() + PENDING_SECONDS}
            return "Tu es sûr ? Je perdrai tout ce que je sais de toi. Dis « oui, oublie tout » pour confirmer."

        if P_UNDO.match(f):
            return self._undo()

        if P_THANKS.match(f):
            if prev:
                self.mem.set_feedback(prev["id"], 1)
            return pick("Avec plaisir !", "Toujours là pour ça.", "Content que ça te plaise !", "De rien !")

        if P_WRONG.match(f):
            if prev:
                self.mem.set_feedback(prev["id"], -1)
            # On n'apprend un raccourci que si la demande n'avait pas ete comprise (ou avait echoue).
            learn = bool(prev) and (prev["handled_by"] == "llm" or not prev["ok"])
            self.pending = {"kind": "correction", "heard": prev["heard"] if prev else "", "learn": learn,
                            "until": time.time() + PENDING_SECONDS}
            return pick("Oups, désolé. Qu'est-ce que tu voulais exactement ?",
                        "Pardon, j'ai dû mal comprendre. Dis-moi ce que tu voulais.",
                        "Désolé pour ça. Redis-moi ce que tu voulais, je m'en souviendrai.")

        m = P_MEANT.match(f)
        if m and prev:
            return self._correct(prev["heard"], span(m), pipeline, learn=True)   # « j'ai dit ... » : explicite
        m = P_WRONG_THEN.match(f)
        if m and not P_THANKS.match(m.group(1)):
            if prev:
                self.mem.set_feedback(prev["id"], -1)
            return self._run_with_prefix(span(m), pipeline, pick("Pardon ! ", "Désolé, j'ai mal compris. ", "Oups. "))

        m = P_NAME.match(f)
        if m:
            name = span(m).title()
            self.mem.add_fact(name, key="name")
            return pick(f"Enchanté {name} ! Je m'en souviendrai.", f"Très bien {name}, c'est noté.")
        m = P_REMEMBER.match(f)
        if m:
            self.mem.add_fact(span(m))
            return pick("C'est noté, je m'en souviendrai.", "Bien reçu, je retiens ça.", "D'accord, c'est gravé dans ma mémoire.")
        m = P_FORGET_FACT.match(f)
        if m:
            n = self.mem.forget_facts(span(m))
            return "Ok, c'est oublié." if n else "Je ne me souvenais pas de ça."
        if P_FORGET_ALIAS.match(f):
            alias = self.mem.delete_last_alias()
            return (f"D'accord, j'oublie que « {alias['phrase']} » voulait dire « {alias['target']} »."
                    if alias else "Je n'ai aucune correction à oublier.")
        if P_KNOW.match(f):
            return self._know()
        if P_LEARNED.match(f):
            als = self.mem.aliases()[:5]
            if not als:
                return "Pour l'instant, tu ne m'as corrigé sur rien."
            return "J'ai retenu : " + " ; ".join(f"quand tu dis « {a['phrase']} », tu veux dire « {a['target']} »" for a in als) + "."
        if P_BILAN.match(f):
            return self._bilan()
        if P_FAVORITE.search(f):
            top = self._top_channels(1)
            if not top:
                return "Je ne t'ai pas encore vu regarder assez de chaînes pour deviner ta préférée."
            name = top[0][0]
            reply, _ = pipeline(f"mets {name}")
            return pick(f"Ta chaîne habituelle, donc {name}.", f"Comme d'habitude, {name} !") \
                if "ne répond pas" not in reply else reply
        if self.pending and self.pending["kind"] == "correction":
            heard, learn = self.pending["heard"], self.pending["learn"]
            self.pending = None
            return self._correct(heard, raw, pipeline, learn)
        return None

    # ------------------------------------------------------------ corrections
    def _run_with_prefix(self, command: str, pipeline, prefix: str) -> str:
        reply, _ = pipeline(command)
        return prefix + reply

    def _correct(self, heard: str, wanted: str, pipeline, learn: bool) -> str:
        reply, _ = pipeline(wanted)
        if learn and heard and phrase_key(heard) and phrase_key(heard) != phrase_key(wanted):
            self.mem.add_alias(phrase_key(heard), wanted)
            log.info("Correction apprise : %r -> %r", heard, wanted)
            return pick("Merci, je m'en souviendrai. ", "Compris, la prochaine fois je ferai comme ça. ",
                        "Noté ! J'ai retenu la leçon. ") + reply
        return reply

    # ------------------------------------------------------------ annuler
    def _undo(self) -> str:
        acts_rows = self.mem.last_interactions(1, with_actions=True)
        if not acts_rows:
            return "Je n'ai rien à annuler pour l'instant."
        target = acts_rows[0]
        inverses = []
        for a in reversed(target["actions"]):
            inv = self._inverse(a, target["id"])
            if inv is None:
                return "Désolé, je ne sais pas comment annuler ça."
            inverses.append(inv)
        for name, args in inverses:
            self.dispatch(name, args)
        self.mem.set_feedback(target["id"], UNDONE)
        self._mark_undone = True
        return pick("C'est annulé.", "Voilà, j'ai remis comme avant.", "Ok, retour en arrière.")

    def _inverse(self, action: dict, interaction_id: int):
        tool, args = action.get("tool"), action.get("args", {})
        swap = {"up": "down", "down": "up", "mute": "unmute", "unmute": "mute",
                "channel_up": "channel_down", "channel_down": "channel_up"}
        if tool == "system_volume" and args.get("action") in ("up", "down", "mute", "unmute"):
            return "system_volume", {"action": swap[args["action"]]}
        if tool != "tv_control":
            return None
        act = args.get("action")
        if act == "button":
            v = str(args.get("value", "")).upper()
            other = {"VOLUMEUP": "VOLUMEDOWN", "VOLUMEDOWN": "VOLUMEUP", "MUTE": "MUTE"}.get(v)
            return ("tv_control", {**args, "value": other}) if other else None
        if act in ("channel_up", "channel_down", "mute", "unmute"):
            return "tv_control", {**args, "action": swap[act]}
        if act == "set_volume" and "previous" in args:
            return "tv_control", {"action": "set_volume", "value": str(args["previous"])}
        if act == "goto_channel":
            before = self.mem.interactions_before(interaction_id, "tv_control", "goto_channel", 1)
            if before:
                return "tv_control", {"action": "goto_channel", "value": str(before[0]["args"]["value"]),
                                      "name": before[0]["args"].get("name", "")}
        return None

    # ------------------------------------------------------------ bilans
    def _top_channels(self, n: int) -> list:
        counter: Counter = Counter()
        for acts, ok, fb, by in self.mem.all_actions():
            for a in acts:
                args = a.get("args", {})
                if a.get("tool") == "tv_control" and args.get("action") == "goto_channel" and a.get("ok") and fb != UNDONE:
                    counter[args.get("name") or f"la chaîne {args.get('value')}"] += 1
        return counter.most_common(n)

    def _know(self) -> str:
        facts = self.mem.facts()
        top = self._top_channels(2)
        bits = [f["text"] for f in facts if f["key"] != "name"]
        if self.mem.name():
            bits.insert(0, f"tu t'appelles {self.mem.name()}")
        if top:
            bits.append("tu regardes souvent " + " et ".join(n for n, _ in top))
        return ("Voilà ce que je sais : " + " ; ".join(bits) + ".") if bits else \
            "Pas grand-chose pour l'instant. Dis-moi « souviens-toi que… » pour m'apprendre des choses."

    def _bilan(self) -> str:
        rows = self.mem.all_actions()
        total = self.mem.count()
        if not total:
            return "Je viens juste de commencer à noter, je n'ai pas encore de bilan à te faire."
        direct = sum(1 for _, _, _, by in rows if by == "direct")
        llm = sum(1 for _, _, _, by in rows if by == "llm")
        failed = sum(1 for acts, ok, _, _ in rows if acts and not ok)
        negative = sum(1 for _, _, fb, _ in rows if fb == -1)
        positive = sum(1 for _, _, fb, _ in rows if fb == 1)
        parts = [f"On a échangé {total} fois : {direct} commande{'s' if direct > 1 else ''} directe{'s' if direct > 1 else ''} "
                 f"et {llm} réponse{'s' if llm > 1 else ''} réfléchie{'s' if llm > 1 else ''}."]
        if failed:
            parts.append(f"{failed} actions ont échoué.")
        if negative:
            n_alias = len(self.mem.aliases())
            parts.append(f"Tu m'as corrigé {negative} fois, j'ai appris {n_alias} raccourci{'s' if n_alias > 1 else ''}.")
        if positive:
            parts.append(f"Et tu m'as remercié {positive} fois, ça fait plaisir.")
        return " ".join(parts)

"""Build every diagram under docs/img from code.

    uv run python docs/build_diagrams.py              # all three
    uv run python docs/build_diagrams.py deployment   # just one

SVG is the source of truth; PNG is rendered from it so the docs can embed either. The two
hand-drawn diagrams use absolute coordinates on purpose: the layout carries meaning, and a
generator that re-flows it would lose that. The process flow uses Graphviz because its edges
carry numbers, not words, so there is nothing to place by hand.
"""
import sys
import tempfile
from pathlib import Path

DOCS = Path(__file__).resolve().parent
IMG = DOCS / "img"

INK = "#232f3e"
PURPLE = "#8c4fff"
ORANGE = "#ed7100"
GREEN = "#3f8624"
BLUE = "#527fff"
GRAY = "#687078"
RED = "#d13212"
BAND = "#fafbfc"
WHITE = "#ffffff"
FONT = "-apple-system, Segoe UI, Helvetica, Arial"


class Canvas:
    """A minimal SVG builder: one list of elements, plus the arrow markers in use."""

    def __init__(self, width: int, height: int, *, markers=()):
        self.width, self.height = width, height
        self.parts: list[str] = []
        self.markers = tuple(markers)

    def add(self, element: str) -> None:
        self.parts.append(element)

    def save(self, name: str) -> None:
        """Write img/<name>.svg and render img/<name>.png beside it."""
        IMG.mkdir(exist_ok=True)
        svg = self._assemble()
        (IMG / f"{name}.svg").write_text(svg)
        render_png(IMG / f"{name}.svg", IMG / f"{name}.png")
        print(f"wrote img/{name}.svg and img/{name}.png")

    def _assemble(self) -> str:
        head = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
                f'height="{self.height}" viewBox="0 0 {self.width} {self.height}" '
                f'font-family="{FONT}">',
                f'<rect width="{self.width}" height="{self.height}" fill="{WHITE}"/>']
        for colour in self.markers:
            head.append(
                f'<defs><marker id="a{colour.strip("#")}" markerWidth="8" markerHeight="8" '
                f'refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="{colour}"/>'
                f'</marker></defs>')
        return "\n".join([*head, *self.parts, "</svg>"])


# --- primitives shared by more than one diagram ---------------------------------------------

def card(c: Canvas, x, y, w, h, stroke, title, lines, *, dash=None, muted=False, r=8):
    """A service card: coloured border, bold title, caption lines."""
    d = f' stroke-dasharray="{dash}"' if dash else ""
    c.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{WHITE}" '
          f'stroke="{stroke}" stroke-width="2"{d}/>')
    ink = GRAY if muted else INK
    c.add(f'<text x="{x + w / 2}" y="{y + 24}" text-anchor="middle" font-size="13.5" '
          f'font-weight="600" fill="{ink}">{title}</text>')
    for i, line in enumerate(lines):
        c.add(f'<text x="{x + w / 2}" y="{y + 42 + i * 15}" text-anchor="middle" '
              f'font-size="11" fill="{GRAY}">{line}</text>')


def pill(c: Canvas, x, y, w, h, title, sub):
    c.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{WHITE}" '
          f'stroke="{INK}" stroke-width="2"/>')
    c.add(f'<text x="{x + w / 2}" y="{y + h / 2 - 1}" text-anchor="middle" font-size="13" '
          f'font-weight="600" fill="{INK}">{title}</text>')
    c.add(f'<text x="{x + w / 2}" y="{y + h / 2 + 14}" text-anchor="middle" font-size="10" '
          f'fill="{GRAY}">{sub}</text>')


def boundary(c: Canvas, x, y, w, h, label):
    c.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{BAND}" '
          f'stroke="{GRAY}" stroke-width="1.5" stroke-dasharray="7 5"/>')
    c.add(f'<text x="{x + 14}" y="{y + 21}" font-size="11" font-weight="700" fill="{GRAY}" '
          f'letter-spacing="0.8">{label}</text>')


def heading(c: Canvas, title: str, sub: str, *, x=40, y=42):
    c.add(f'<text x="{x}" y="{y}" font-size="20" font-weight="700" fill="{INK}">{title}</text>')
    c.add(f'<text x="{x}" y="{y + 22}" font-size="12" fill="{GRAY}">{sub}</text>')


def hline(c: Canvas, x1, x2, y, label="", *, color=GRAY):
    c.add(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="1.8" '
          f'marker-end="url(#a{color.strip("#")})"/>')
    if label:
        c.add(f'<text x="{(x1 + x2) / 2}" y="{y - 7}" text-anchor="middle" font-size="10" '
              f'fill="{GRAY}">{label}</text>')


def vline(c: Canvas, x, y1, y2, label="", *, color=GRAY):
    c.add(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{color}" stroke-width="1.8" '
          f'marker-end="url(#a{color.strip("#")})"/>')
    if label:
        c.add(f'<text x="{x + 8}" y="{(y1 + y2) / 2 + 4}" font-size="10" fill="{GRAY}">'
              f'{label}</text>')


def state(c: Canvas, x, y, w, name, sub="", *, stroke=PURPLE, fill=WHITE):
    h = 46 if sub else 38
    c.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h / 2}" fill="{fill}" '
          f'stroke="{stroke}" stroke-width="2"/>')
    ty = y + h / 2 + (0 if not sub else -4)
    c.add(f'<text x="{x + w / 2}" y="{ty + 4}" text-anchor="middle" font-size="11.5" '
          f'font-weight="600" fill="{INK}">{name}</text>')
    if sub:
        c.add(f'<text x="{x + w / 2}" y="{ty + 16}" text-anchor="middle" font-size="9" '
              f'fill="{GRAY}">{sub}</text>')


def route(c: Canvas, pts, label="", *, lx=0, ly=0, color=GRAY, dash=None, anchor="middle",
          size=9.5):
    d = "M" + " L".join(f"{x},{y}" for x, y in pts)
    dd = f' stroke-dasharray="{dash}"' if dash else ""
    c.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"{dd} '
          f'marker-end="url(#a{color.strip("#")})"/>')
    if label:
        c.add(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="{size}" '
              f'fill="{GRAY}">{label}</text>')


def render_png(svg: Path, png: Path, scale: str = "2") -> None:
    import subprocess

    subprocess.run(["rsvg-convert", "-z", scale, str(svg), "-o", str(png)], check=True)


# --- 1. deployment --------------------------------------------------------------------------

def deployment() -> None:
    """Where each part runs: the runtime session, its services, and the firm's systems."""
    c = Canvas(1210, 720, markers=(PURPLE, ORANGE, GREEN, BLUE, GRAY, INK))
    heading(c, "NovaMark research workforce: deployment",
            "One AgentCore Runtime session per run, inside NovaMark's AWS account.")

    pill(c, 40, 116, 170, 54, "Analyst", "submits the request")
    pill(c, 40, 300, 170, 54, "Reviewer", "senior analyst / compliance officer")

    boundary(c, 250, 92, 620, 470, "NOVAMARK AWS ACCOUNT, THEIR REGION")
    c.add(f'<rect x="270" y="118" width="240" height="290" rx="10" fill="{WHITE}" '
          f'stroke="{PURPLE}" stroke-width="2" stroke-dasharray="7 5"/>')
    c.add(f'<text x="284" y="138" font-size="10.5" font-weight="700" fill="{PURPLE}" '
          f'letter-spacing="0.5">AGENTCORE RUNTIME, ONE MICROVM</text>')
    card(c, 288, 152, 204, 68, ORANGE, "agent.py",
         ["entrypoint, SigV4", "new_request / decision"])
    card(c, 288, 252, 204, 68, ORANGE, "pipeline",
         ["intake to synthesis,", "two gates inside"])

    card(c, 580, 118, 240, 62, PURPLE, "Bedrock", ["model inference, their region"])
    card(c, 580, 210, 240, 62, GREEN, "S3", ["one MemoState per run_id"])
    card(c, 580, 302, 240, 62, GRAY, "CloudWatch", ["traces and logs"])
    card(c, 288, 340, 204, 52, INK, "mocks, in this process",
         ["market quote, research KB over stdio"])

    boundary(c, 890, 92, 280, 470, "NOT CONNECTED")
    card(c, 908, 160, 244, 62, GRAY, "Market system", ["not called"], muted=True, dash="5 4")
    card(c, 908, 250, 244, 62, GRAY, "Research database", ["not called"], muted=True, dash="5 4")
    card(c, 908, 340, 244, 62, GRAY, "ESG provider", ["not called"], muted=True, dash="5 4")
    hline(c, 210, 286, 143, "1 request")
    hline(c, 286, 212, 172, "2 gate packet")
    hline(c, 212, 286, 327, "3 decision")
    vline(c, 390, 220, 250, "4 MemoState")

    # one spine off the pipeline, four short spurs, so no two routes share a segment
    spine = 548
    c.add(f'<line x1="492" y1="286" x2="{spine}" y2="286" stroke="{GRAY}" stroke-width="1.8"/>')
    c.add(f'<line x1="{spine}" y1="149" x2="{spine}" y2="333" stroke="{GRAY}" '
          f'stroke-width="1.8"/>')
    for y, label in ((149, "5 model calls"), (241, "6 save / load"), (333, "7 spans")):
        c.add(f'<line x1="{spine}" y1="{y}" x2="578" y2="{y}" stroke="{GRAY}" '
              f'stroke-width="1.8" marker-end="url(#a{GRAY.strip("#")})"/>')
        c.add(f'<text x="{(spine + 578) / 2}" y="{y - 6}" text-anchor="middle" font-size="9.5" '
              f'fill="{GRAY}">{label}</text>')

    c.add(f'<line x1="390" y1="320" x2="390" y2="340" stroke="{GRAY}" stroke-width="1.8" '
          f'marker-end="url(#a{GRAY.strip("#")})"/>')

    boundary(c, 40, 400, 180, 162, "LEGEND")
    legend_rows = [(ORANGE, "compute"), (PURPLE, "model or agent"), (BLUE, "integration"),
                   (GREEN, "storage"), (GRAY, "observability")]
    for i, (colour, label) in enumerate(legend_rows):
        y = 432 + i * 24
        c.add(f'<rect x="58" y="{y}" width="24" height="14" rx="3" fill="{WHITE}" '
              f'stroke="{colour}" stroke-width="2"/>')
        c.add(f'<text x="90" y="{y + 11}" font-size="11" fill="{GRAY}">{label}</text>')
    c.add(f'<rect x="58" y="552" width="24" height="14" rx="3" fill="{WHITE}" stroke="{GRAY}" '
          f'stroke-width="2" stroke-dasharray="5 4"/>')
    c.add(f'<text x="90" y="563" font-size="11" fill="{GRAY}">not connected</text>')

    c.add(f'<text x="40" y="612" font-size="12.5" font-weight="700" fill="{INK}">'
          f'Two things that break in their account and do not break locally</text>')
    c.add(f'<text x="40" y="634" font-size="11.5" fill="{GRAY}">'
          f'The US inference profile can send a prompt to another US region. A local call '
          f'has no residency check that fails.</text>')
    c.add(f'<text x="40" y="654" font-size="11.5" fill="{GRAY}">'
          f'The research client starts a subprocess on this machine. Their research server '
          f'is not on that machine.</text>')

    c.save("deployment")


# --- 2. state machine -----------------------------------------------------------------------

def note(c: Canvas, x, y, text, *, color=GRAY, anchor="middle", size=9.5):
    c.add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}" '
          f'fill="{color}">{text}</text>')


def state_machine() -> None:
    """The states a run is in (its `status`), and what moves it from one to the next."""
    c = Canvas(1440, 500, markers=(PURPLE, GRAY, ORANGE, RED, GREEN))
    heading(c, "State machine",
            "Boxes are the states a run is in. Arrows are the process, or the person's decision, "
            "that moves it on.", x=34, y=38)

    state(c, 30, 210, 128, "data_collector")
    state(c, 270, 210, 150, "document_analyser")
    state(c, 560, 204, 140, "senior_review", "senior analyst", stroke=ORANGE, fill="#fff7e8")
    state(c, 840, 210, 100, "synthesis")
    state(c, 1060, 204, 152, "compliance_review", "compliance officer", stroke=GREEN,
          fill="#eef8ea")
    state(c, 1320, 210, 104, "published", stroke=GREEN)
    state(c, 760, 400, 120, "escalated", stroke=RED)

    route(c, [(158, 229), (268, 229)])
    note(c, 213, 206, "collect +")
    note(c, 213, 218, "prior_research")
    route(c, [(420, 229), (558, 229)])
    note(c, 489, 206, "analyse:")
    note(c, 489, 218, "flagged")
    route(c, [(700, 229), (838, 229)], color=ORANGE)
    note(c, 769, 206, "approve or", color=ORANGE)
    note(c, 769, 218, "amend", color=ORANGE)
    route(c, [(940, 229), (1058, 229)])
    note(c, 999, 222, "synthesize")
    route(c, [(1212, 229), (1318, 229)], color=GREEN)
    note(c, 1265, 206, "approve or", color=GREEN)
    note(c, 1265, 218, "amend", color=GREEN)

    route(c, [(345, 208), (345, 125), (870, 125), (870, 208)])
    note(c, 607, 118, "analyse: clean, no review")

    route(c, [(590, 250), (590, 320), (345, 320), (345, 250)], color=RED, dash="5 4")
    note(c, 467, 334, "reject: analyse again", color=RED)
    route(c, [(1136, 206), (1136, 170), (910, 170), (910, 208)], color=RED, dash="5 4")
    note(c, 1023, 164, "reject: synthesize again", color=RED)

    route(c, [(670, 250), (670, 419), (758, 419)], color=RED, dash="5 4")
    note(c, 678, 330, "third reject", color=RED, anchor="start")
    route(c, [(1100, 250), (1100, 419), (882, 419)], color=RED, dash="5 4")
    note(c, 1108, 330, "third reject", color=RED, anchor="start")

    c.add(f'<rect x="34" y="346" width="14" height="14" rx="4" fill="#fff7e8" stroke="{ORANGE}" '
          f'stroke-width="2"/>')
    note(c, 58, 358, "waiting for a person", anchor="start", size=10.5)
    c.add(f'<line x1="34" y1="382" x2="62" y2="382" stroke="{RED}" stroke-width="1.8" '
          f'stroke-dasharray="5 4" marker-end="url(#a{RED.strip("#")})"/>')
    note(c, 72, 386, "rejection, back to the producer", anchor="start", size=10.5)
    note(c, 34, 418, "published and escalated are terminal.", anchor="start", size=10.5)
    note(c, 34, 440, "Every arrow hands on the same MemoState with its status changed.",
         anchor="start", size=10.5)

    c.save("state-machine")


# --- 5. execution sequence ------------------------------------------------------------------

def frame(c: Canvas, x, y, w, h, label, color):
    c.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="none" stroke="{color}" '
          f'stroke-width="1.3" stroke-dasharray="6 4"/>')
    c.add(f'<text x="{x + 8}" y="{y + 14}" font-size="9.5" font-weight="700" fill="{color}" '
          f'letter-spacing="0.5">{label}</text>')


def reply(c: Canvas, x1, x2, y, label, *, color=GRAY):
    """A dashed return arrow, label above the line."""
    c.add(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="1.6" '
          f'stroke-dasharray="5 4" marker-end="url(#a{color.strip("#")})"/>')
    note(c, (x1 + x2) / 2, y - 7, label, color=GRAY)


def span(c: Canvas, x1, x2, y, label):
    """A telemetry span sent to CloudWatch, one per advance pass or model call."""
    c.add(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{PURPLE}" stroke-width="1.4" '
          f'stroke-dasharray="2 3" marker-end="url(#a{PURPLE.strip("#")})"/>')
    note(c, (x1 + x2) / 2, y - 7, label, color=PURPLE)


def execution() -> None:
    """One request through the orchestrator: transitions, the model turn, failures, telemetry."""
    c = Canvas(1340, 920, markers=(GRAY, RED, BLUE, ORANGE, GREEN, PURPLE))
    heading(c, "Execution: how the orchestrator runs the transitions",
            "Each pass of the loop runs the process that `status` names, and gets back a new "
            "state. Failures and telemetry are shown where they happen.", x=34, y=38)

    xs = {"client": 100, "agent": 280, "orch": 460, "proc": 640, "llm": 820, "store": 1000,
          "cw": 1180}
    for key, title, sub, colour in (
            ("client", "Client", "analyst or reviewer", INK),
            ("agent", "agent.py", "runtime entrypoint", ORANGE),
            ("orch", "Orchestrator", "advance loop", ORANGE),
            ("proc", "Process", "collect, analyse, synthesize", ORANGE),
            ("llm", "Strands agent", "one turn, then Bedrock", PURPLE),
            ("store", "S3", "snapshots", GREEN),
            ("cw", "CloudWatch", "logs, spans", GRAY)):
        card(c, xs[key] - 75, 80, 150, 56, colour, title, [sub])
        lifeline(c, xs[key], 136, 880)

    hline(c, xs["client"], xs["agent"], 176, "1 invoke(payload)")
    hline(c, xs["agent"], xs["orch"], 216, "2 start or decide_sync")
    note(c, 370, 232, "intake, or load the latest snapshot", size=9)

    frame(c, 410, 250, 480, 266, "LOOP: WHILE STATUS NAMES A PROCESS", BLUE)
    hline(c, xs["orch"], xs["proc"], 292, "3 STEPS[status](state, deps)")
    hline(c, xs["proc"], xs["llm"], 338, "4 model.ask(prompt)")
    note(c, 730, 353, "in a worker thread", size=9)
    callout(c, 735, 366, 170, ["the agent loop: one Bedrock", "turn, no tools, text back"])
    span(c, xs["llm"], xs["cw"], 426, "span: model call")
    reply(c, xs["llm"], xs["proc"], 452, "5 text")
    reply(c, xs["proc"], xs["orch"], 484, "6 new state, status set to the next process")
    span(c, xs["orch"], xs["cw"], 506, "span: one per transition")

    frame(c, 240, 536, 1000, 226, "ON FAILURE", ORANGE)
    note(c, 250, 568, "a source fails (market, knowledge base)", anchor="start", size=9.5)
    callout(c, 560, 548, 160, ["a gap is added to the", "state; the loop goes on"])
    c.add(f'<line x1="240" y1="606" x2="1240" y2="606" stroke="{ORANGE}" stroke-width="1" '
          f'stroke-dasharray="3 4"/>')
    note(c, 250, 626, "evidence check or model JSON fails", anchor="start", size=9.5)
    hline(c, xs["proc"], xs["orch"], 650, "raises EvidenceError", color=RED)
    hline(c, xs["orch"], xs["agent"], 680, "propagates", color=RED)
    hline(c, xs["agent"], xs["cw"], 710, "ERROR with traceback", color=RED)
    reply(c, xs["agent"], xs["client"] + 4, 740, "HTTP 500, no new snapshot", color=RED)

    hline(c, xs["orch"], xs["store"], 790, "7 save a snapshot, at a review or the end",
          color=GREEN)
    reply(c, xs["orch"], xs["client"] + 4, 836, "8 review packet or result")

    callout(c, 1055, 250, 250, ["CloudWatch: INFO logs, and the", "traceback when invoke fails.",
            "Spans for each transition and", "model call go to Transaction Search."])

    c.add(f'<line x1="34" y1="896" x2="62" y2="896" stroke="{PURPLE}" stroke-width="1.4" '
          f'stroke-dasharray="2 3" marker-end="url(#a{PURPLE.strip("#")})"/>')
    note(c, 72, 900, "span: one advance pass or one model call, exported to CloudWatch",
         anchor="start", size=10)

    c.save("execution")


# --- 4. identity ----------------------------------------------------------------------------

def lifeline(c: Canvas, x, y1, y2):
    c.add(f'<line x1="{x}" y1="{y1}" x2="{x}" y2="{y2}" stroke="{GRAY}" stroke-width="1.2" '
          f'stroke-dasharray="4 4"/>')


def callout(c: Canvas, x, y, w, lines, *, color=GRAY, fill=WHITE):
    h = 12 + 15 * len(lines)
    c.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" '
          f'stroke="{color}" stroke-width="1.5"/>')
    for i, line in enumerate(lines):
        c.add(f'<text x="{x + w / 2}" y="{y + 19 + i * 15}" text-anchor="middle" '
              f'font-size="10.5" fill="{INK}">{line}</text>')


def badge(c: Canvas, x, y, text, color, w=176):
    """The identity a component holds at this point, centred on its lifeline."""
    c.add(f'<rect x="{x - w / 2}" y="{y}" width="{w}" height="22" rx="11" fill="{WHITE}" '
          f'stroke="{color}" stroke-width="1.5"/>')
    c.add(f'<text x="{x}" y="{y + 15}" text-anchor="middle" font-size="10" font-weight="600" '
          f'fill="{color}">{text}</text>')


def identity() -> None:
    """How the identity that ran the memo came to exist, from deploy to the saved record."""
    c = Canvas(1240, 880, markers=(GRAY, ORANGE, PURPLE, GREEN, RED))
    heading(c, "Identity: how the agent that ran the memo got its identity",
            "Pills show who each component acts as. The client's identity gets through the door; "
            "the runtime role does the work.", x=34, y=38)

    xs = {"deployer": 100, "client": 290, "runtime": 480, "iam": 670, "agent": 860, "aws": 1050}
    for key, title, sub, colour in (
            ("deployer", "Deployer", "cdk deploy", INK),
            ("client", "Client", "analyst or reviewer", INK),
            ("runtime", "AgentCore Runtime", "invoke endpoint", ORANGE),
            ("iam", "IAM and STS", "identity and permissions", GRAY),
            ("agent", "agent.py", "runs as the runtime role", ORANGE),
            ("aws", "Bedrock and S3", "model and state", PURPLE)):
        card(c, xs[key] - 80, 80, 160, 56, colour, title, [sub])
        lifeline(c, xs[key], 136, 840)

    frame(c, 40, 156, 1160, 126, "ONCE, AT DEPLOY", GRAY)
    hline(c, xs["deployer"], xs["iam"], 204, "A create the runtime role, trusted by the AgentCore service")
    badge(c, xs["deployer"], 214, "acts as: deployer", INK, 116)
    badge(c, xs["iam"], 214, "RuntimeRole now exists", GRAY)
    hline(c, xs["deployer"], xs["runtime"], 252, "B create the runtime, naming that role")
    badge(c, xs["runtime"], 258, "bound to: RuntimeRole", ORANGE)

    frame(c, 40, 296, 1160, 528, "FOR EACH REQUEST", BLUE)
    hline(c, xs["client"], xs["runtime"], 340, "1 POST /invocations, SigV4-signed")
    badge(c, xs["client"], 350, "acts as: client principal", BLUE)
    badge(c, xs["runtime"], 350, "caller: client principal", BLUE)
    hline(c, xs["runtime"], xs["iam"], 406, "2 verify the signature and the invoke permission")
    reply(c, xs["iam"], xs["runtime"], 436, "allow, or 403 and nothing runs")
    hline(c, xs["runtime"], xs["iam"], 484, "3 assume the runtime role")
    reply(c, xs["iam"], xs["runtime"], 514, "temporary credentials for the session")
    badge(c, xs["runtime"], 524, "acts as: RuntimeRole", ORANGE)
    hline(c, xs["runtime"], xs["agent"], 580, "4 start the session; invoke(payload)")
    badge(c, xs["agent"], 590, "acts as: RuntimeRole", ORANGE)
    hline(c, xs["agent"], xs["aws"], 646, "5 InvokeModel, put snapshot")
    badge(c, xs["aws"], 656, "caller: RuntimeRole", ORANGE)
    note(c, 385, 626, "the client's identity stops at the runtime; it is not passed on", size=9)

    callout(c, 640, 696, 340, ["6 the saved record names who did what:",
            "values: model_id, produced_at, step"])
    callout(c, 640, 746, 340, ["decisions: reviewer, as sent in the payload,",
            "not verified against the client's identity"], color=RED, fill="#fdf0ee")
    reply(c, xs["agent"], xs["client"] + 4, 804, "7 review packet or result")

    c.save("identity")


# --- 3. process flow ------------------------------------------------------------------------

STEPS = [
    "request: ticker, asset class, analysis type",
    "MemoState: the typed state is created",
    "sources: filing text, with citations",
    "prior memos, or a gap if the server fails",
    "values and risk: a citation and confidence each",
    "clean: every confidence at or above 0.75",
    "flagged: a confidence under 0.75, or high risk",
    "approve or amend",
    "reject: the analyser runs again",
    "memo: the draft for sign-off",
    "approve: published",
    "reject: the memo is rewritten",
]

DOT = """
digraph flow {
  rankdir=LR;
  splines=spline;
  nodesep=0.55;
  ranksep=0.70;
  bgcolor="white";
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10,
        color="#8c4fff", fillcolor="white", penwidth=1.8, height=0.40, margin="0.12,0.04"];
  edge [fontname="Helvetica", fontsize=8, fontcolor="#687078", color="#687078",
        arrowsize=0.65, penwidth=1.3];

  analyst [label="Analyst", color="#232f3e"];
  intake [label="intake"];
  collector [label="data_collector"];
  analyser [label="document_analyser"];
  check [label="evidence_check"];
  synth [label="synthesis"];
  published [label="published", color="#3f8624", fillcolor="#eef8ea"];
  senior [label="Senior analyst", color="#ff9900", fillcolor="#fff7e8"];
  compliance [label="Compliance officer", color="#ff9900", fillcolor="#fff7e8"];
  kb [label="Research KB", shape=cylinder, color="#527fff", fillcolor="#f4f6f8"];

  analyst -> intake [label="1"];
  intake -> collector [label="2"];
  collector -> analyser [label="3"];
  kb -> analyser [label="4", fontcolor="#527fff"];
  analyser -> check [label="5"];
  check -> synth [label="6"];
  check -> senior [label="7", fontcolor="#ff9900", color="#ff9900"];
  senior -> synth [label="8", fontcolor="#ff9900", color="#ff9900"];
  senior -> analyser [label="9", fontcolor="#d13212", color="#d13212",
                      style=dashed, constraint=false];
  synth -> compliance [label="10"];
  compliance -> published [label="11", fontcolor="#ff9900", color="#ff9900"];
  compliance -> synth [label="12", fontcolor="#d13212", color="#d13212",
                       style=dashed, constraint=false];

  {rank=same; analyst; intake;}
  {rank=same; senior; analyser;}
  {rank=same; compliance; synth;}
}
"""


def _legend_svg() -> str:
    """A two-column list of the numbered steps, keyed to the graph's edge labels."""
    rows = "".join(
        f'<text x="{34 + (i - 1) // 6 * 460}" y="{34 + ((i - 1) % 6) * 20}" font-size="11" '
        f'font-weight="700" fill="#5a6b7b">{i}</text>'
        f'<text x="{52 + (i - 1) // 6 * 460}" y="{34 + ((i - 1) % 6) * 20}" font-size="11" '
        f'fill="#3a4553">{text}</text>'
        for i, text in enumerate(STEPS, 1))
    height = 34 + 6 * 20
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="920" height="{height}" '
            f'font-family="{FONT}"><rect width="920" height="{height}" fill="white"/>'
            f'{rows}</svg>')


def process_flow() -> None:
    """The requirements flow. Graphviz lays it out; the numbered legend is appended below.

    Edge labels are single digits so nothing has to fit on a line, and the wording lives in the
    legend where it stays readable at any width.
    """
    import re
    import subprocess

    IMG.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "flow.dot").write_text(DOT)
        svg = subprocess.run(["dot", "-Tsvg", str(tmp / "flow.dot")], capture_output=True,
                             text=True, check=True).stdout
        svg = re.sub(r'font-family="[^"]*"', f'font-family="{FONT}"', svg)
        (IMG / "process-flow.svg").write_text(svg)

        (tmp / "legend.svg").write_text(_legend_svg())
        render_png(IMG / "process-flow.svg", tmp / "graph.png")
        render_png(tmp / "legend.svg", tmp / "legend.png")
        subprocess.run(["magick", str(tmp / "graph.png"), str(tmp / "legend.png"), "-append",
                        str(IMG / "process-flow.png")], check=True)
    print("wrote img/process-flow.svg and img/process-flow.png")


# --- entrypoint -----------------------------------------------------------------------------

DIAGRAMS = {
    "deployment": deployment,
    "state-machine": state_machine,
    "process-flow": process_flow,
    "identity": identity,
    "execution": execution,
}


def main(argv: list[str]) -> int:
    wanted = argv[1:] or list(DIAGRAMS)
    unknown = [name for name in wanted if name not in DIAGRAMS]
    if unknown:
        print(f"unknown diagram(s): {', '.join(unknown)}")
        print(f"choose from: {', '.join(DIAGRAMS)}")
        return 2
    for name in wanted:
        DIAGRAMS[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

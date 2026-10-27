"""Generate the Matchcut Azure architecture diagram (component and deployment view, as built).

Official Azure icons (V24, unmodified), real boundaries, numbered flows, a line legend and a
metadata block. Output: SVG (GitHub-safe).
Usage: python gen_azure_architecture.py <icons_dir> <out.svg>
"""

import re
import sys
from pathlib import Path

ICONS_DIR = Path(sys.argv[1])
OUT = Path(sys.argv[2])

ICON_FILES = {
    "aca": "other/02884-icon-service-Worker-Container-App.svg",
    "acaenv": "other/02989-icon-service-Container-Apps-Environments.svg",
    "acr": "containers/10105-icon-service-Container-Registries.svg",
    "st": "storage/10086-icon-service-Storage-Accounts.svg",
    "queue": "general/10840-icon-service-Storage-Queue.svg",
    "blob": "general/10780-icon-service-Blob-Block.svg",
    "foundry": "ai + machine learning/038470614-icon-service-Foundry-Models.svg",
    "speech": "ai + machine learning/00797-icon-service-Speech-Services.svg",
    "mi": "identity/10227-icon-service-Managed-Identities.svg",
    "appi": "monitor/00012-icon-service-Application-Insights.svg",
    "law": "monitor/00009-icon-service-Log-Analytics-Workspaces.svg",
    "cost": "general/10019-icon-service-Cost-Management.svg",
    "rg": "general/10007-icon-service-Resource-Groups.svg",
    "sub": "general/10002-icon-service-Subscriptions.svg",
}

FONT = "'Segoe UI', Inter, system-ui, -apple-system, Helvetica, Arial, sans-serif"
INK, MUTED, LINE = "#1B1F24", "#5B6573", "#3F4A57"
SIGNAL = "#E8432A"  # brand accent, used only for Matchcut-owned code

_counter = [0]


def icon(key, x, y, size=52):
    """Embed an official icon unmodified, prefixing ids so gradients don't collide."""
    raw = (ICONS_DIR / ICON_FILES[key]).read_text(encoding="utf-8")
    raw = re.sub(r"<\?xml.*?\?>", "", raw)
    _counter[0] += 1
    pfx = f"i{_counter[0]}_"
    raw = re.sub(r'id="([^"]+)"', lambda m: f'id="{pfx}{m.group(1)}"', raw)
    raw = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{pfx}{m.group(1)})", raw)
    raw = re.sub(r'href="#([^"]+)"', lambda m: f'href="#{pfx}{m.group(1)}"', raw)
    vb = re.search(r'viewBox="([^"]+)"', raw)
    inner = re.sub(r"^.*?<svg[^>]*>", "", raw, flags=re.S)
    inner = re.sub(r"</svg>\s*$", "", inner.strip())
    return (
        f'<svg x="{x}" y="{y}" width="{size}" height="{size}" viewBox="{vb.group(1) if vb else "0 0 18 18"}">'
        f"{inner}</svg>"
    )


def text(x, y, s, size=13, weight=400, fill=INK, anchor="start"):
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" style="font:{weight} {size}px {FONT}" '
        f'fill="{fill}">{s}</text>'
    )


def underline(x, y, w=36):
    return f'<rect x="{x}" y="{y}" width="{w}" height="3" rx="1.5" fill="{SIGNAL}"/>'


def node(key, cx, y, title, subs=(), size=52, ours=False):
    """Icon centred, labels below."""
    out = [icon(key, cx - size / 2, y, size), text(cx, y + size + 18, title, 13, 600, INK, "middle")]
    for i, sub in enumerate(subs):
        out.append(text(cx, y + size + 34 + i * 15, sub, 11.5, 400, MUTED, "middle"))
    if ours:
        out.append(underline(cx - 22, y + size + 40 + (len(subs) - 1) * 15, 44))
    return "".join(out)


def side(key, x, y, title, subs=(), size=46, ours=False):
    """Icon left, labels right."""
    out = [icon(key, x, y, size), text(x + size + 12, y + size / 2 - 3, title, 13, 600)]
    for i, sub in enumerate(subs):
        out.append(text(x + size + 12, y + size / 2 + 14 + i * 15, sub, 11.5, 400, MUTED))
    if ours:
        out.append(underline(x + size + 12, y + size / 2 + 22 + (len(subs) - 1) * 15))
    return "".join(out)


def chip(x, y, w, title, subs, ours=True, h=66):
    """A process outside Azure (no Azure icon applies): a card with its name and role."""
    subs = [subs] if isinstance(subs, str) else subs
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#FFFFFF" stroke="#C9CFD7"/>',
        text(x + w / 2, y + 26, title, 13, 600, INK, "middle"),
    ]
    for i, sub in enumerate(subs):
        out.append(text(x + w / 2, y + 44 + i * 15, sub, 11, 400, MUTED, "middle"))
    if ours:
        out.append(underline(x + w / 2 - 18, y + 52 + (len(subs) - 1) * 15))
    return "".join(out)


def boundary(x, y, w, h, label, fill="none", stroke="#9AA4B2", dash="", key=None, r=10, anchor_end=False):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"{d}/>'
    ]
    lx = x + 12
    if key:
        out.append(icon(key, x + 10, y + 8, 18))
        lx = x + 34
    out.append(text(lx, y + 22, label, 12, 600, "#3A4350"))
    return "".join(out)


def badge(n, x, y):
    return f'<circle cx="{x}" cy="{y}" r="10.5" fill="#1B1F24"/>' + text(
        x, y + 4.2, str(n), 11.5 if len(str(n)) < 3 else 10, 700, "#FFFFFF", "middle"
    )


def line(points, style="solid", end=True, start=False):
    d = "M" + " L".join(f"{px} {py}" for px, py in points)
    dash = {"solid": "", "async": ' stroke-dasharray="7 5"', "ident": ' stroke-dasharray="2 4"'}[style]
    m = (' marker-end="url(#ah)"' if end else "") + (' marker-start="url(#ah)"' if start else "")
    return f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="1.5"{dash}{m}/>'


W, H = 1840, 1560
s = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">',
    '<title id="t">Matchcut: Azure architecture (component and deployment view, as built)</title>',
    '<desc id="d">A match pipeline runs before kick-off: the simulator plays the match, Microsoft Agent '
    "Framework agents on Foundry gpt-5-mini write each moment's line with League Memory over MCP, code "
    "verifies every number and Azure AI Speech voices the lines. Images go to Azure Container Registry. "
    "In one resource group, a Container App serves the Studio and the API, and a queue-triggered Container "
    "Apps Job (KEDA, up to 20 replicas) renders moment clips, mixes every language's film, runs the QA agent "
    "(Speech hears, gpt-5-mini reads, code judges) and makes the Recap Factory's fan films. Storage holds the "
    "queue, pieces, films and reports. Everything signs in with a managed identity.</desc>",
    '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#3F4A57"/></marker></defs>',
    f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
]

# Header + metadata
s.append(text(40, 56, "Matchcut · Azure architecture", 26, 700))
s.append(
    text(
        40,
        82,
        "Component and deployment view, as built · where each part runs, how they connect, and the flow from a match to every fan's film",
        14,
        400,
        MUTED,
    )
)
s.append('<rect x="1460" y="30" width="340" height="66" rx="8" fill="#F6F7F9" stroke="#E1E5EA"/>')
s.append(text(1474, 52, "Version 2.1 · 26 Oct 2026 · As built", 12, 600, "#3A4350"))
s.append(text(1474, 70, "Author: Malik Bello · Region: East US 2", 12, 400, MUTED))
s.append(text(1474, 88, "Related: concept diagram · ADR-0004, 0013 to 0016", 12, 400, MUTED))

# People
s.append(boundary(40, 130, 190, 330, "People", "#FAFAFB", "#C9CFD7"))
for i, (who, sub) in enumerate([("Fans", "phone · laptop · TV"), ("Judges", "access code")]):
    cy = 205 + i * 140
    s.append(
        f'<circle cx="135" cy="{cy}" r="15" fill="none" stroke="{INK}" stroke-width="2"/>'
        f'<path d="M108 {cy + 52} Q135 {cy + 16} 162 {cy + 52}" fill="none" stroke="{INK}" stroke-width="2"/>'
    )
    s.append(text(135, cy + 74, who, 13, 600, INK, "middle"))
    s.append(text(135, cy + 90, sub, 11.5, 400, MUTED, "middle"))

# Azure boundaries
s.append(
    boundary(
        270, 120, 1530, 795, "Microsoft Entra ID tenant · Default Directory", "#FBFCFD", "#B7C0CC", "6 4"
    )
)
s.append(
    boundary(
        290, 150, 1490, 750, "Subscription · Azure subscription 1 (Free Trial)", "none", "#9AA4B2", "", "sub"
    )
)
s.append(
    boundary(
        310, 185, 1450, 700, "Resource group · rg-matchcut-dev · East US 2", "#F7F9FC", "#9AA4B2", "", "rg"
    )
)

# Left column: identity, monitoring, cost, registry
s.append(side("mi", 338, 250, "Managed identity", ["keyless · least-privilege roles"]))
s.append(side("appi", 338, 350, "Application Insights", ["agent traces · OpenTelemetry"]))
s.append(side("law", 338, 440, "Log Analytics", ["app and job logs"]))
s.append(side("cost", 338, 530, "Cost Management", ["monthly budget", "alerts at $5 · $10 · $25"]))
s.append(side("acr", 338, 640, "Container Registry", ["api and job images"]))

# Container Apps environment
s.append(
    '<rect x="560" y="215" width="740" height="430" rx="10" fill="#FFFFFF" stroke="#7FA9D6" stroke-width="1.2"/>'
)
s.append(icon("acaenv", 1012, 617, 18))
s.append(text(1036, 631, "Container Apps environment · Consumption", 12, 600, "#3A4350"))
s.append(
    node(
        "aca",
        640,
        262,
        "studio + api",
        ["Container App · 1 warm replica", "Studio · live cues (SSE) · reel", "share pages · Recap Factory"],
        ours=True,
    )
)
s.append(
    '<rect x="860" y="240" width="420" height="360" rx="9" fill="#FBFCFE" stroke="#7FA9D6" stroke-dasharray="4 3"/>'
)
s.append(text(874, 260, "Container Apps Job · KEDA queue trigger · 0 → 20 replicas", 11.5, 600, "#3A4350"))
s.append(side("aca", 876, 276, "render-job", ["4 vCPU · 8 GiB per replica"], 46, ours=True))
for i, t in enumerate(
    [
        "draws each moment with the Studio itself",
        "(headless Chromium, CPU), sliced across replicas",
        "captions it in 7 languages, mixes each film,",
        "and again with audio description",
        "QA agent: hears the film, reads its captions,",
        "measures loudness; code judges",
        "Recap Factory: one fan's film per replica,",
        "checked and priced",
    ]
):
    bullet = i in (0, 2, 4, 6)
    s.append(text(886, 366 + i * 21, ("• " if bullet else "  ") + t, 12, 400, "#2B3240"))

# Storage account
s.append(
    '<rect x="560" y="680" width="740" height="190" rx="10" fill="#FFFFFF" stroke="#9AA4B2" stroke-width="1.2"/>'
)
s.append(icon("st", 572, 838, 18))
s.append(text(596, 852, "Storage account · shared keys off · managed identity only", 12, 600, "#3A4350"))
s.append(node("queue", 640, 716, "Queue · cuts", ["a message per slice or film"], 44))
s.append(node("blob", 960, 716, "Blob · cuts", ["pieces · films · QA reports", "factory runs"], 44))
s.append(node("blob", 1190, 716, "Blob · showcase", ["Studio bundle"], 44))

# AI column
s.append(
    boundary(1340, 215, 420, 655, "Microsoft Foundry · AI Services (one resource)", "#FFFFFF", "#9AA4B2")
)
s.append(
    side(
        "foundry",
        1364,
        262,
        "Foundry Models · gpt-5-mini",
        ["agents write and translate each line", "the QA agent reads captions off frames"],
        52,
    )
)
s.append(
    side(
        "speech",
        1364,
        470,
        "Azure AI Speech",
        ["neural voices: calls, lines, audio description", "fast transcription: QA hears each film"],
        52,
    )
)
s.append(text(1364, 700, "Entra tokens only (no keys)", 11.5, 500, MUTED))

# Outside Azure: the match pipeline and the release
s.append(
    '<rect x="270" y="985" width="1030" height="245" rx="10" fill="#FAFAFB" stroke="#C9CFD7" stroke-width="1.2"/>'
)
s.append(
    text(
        282,
        1220,
        "Build machine (outside Azure) · the match pipeline, a batch run before kick-off · the release",
        12,
        600,
        "#3A4350",
    )
)
s.append(chip(290, 1005, 140, "sim", "match engine · 10 Hz", h=80))
s.append(
    chip(
        470,
        1005,
        250,
        "insights agents",
        ["Agent Framework: Writer · Historian", "code Verifier · Localiser"],
        h=80,
    )
)
s.append(chip(760, 1005, 150, "voices", ["calls · verified lines", "audio description"], h=80))
s.append(chip(950, 1005, 330, "match package", "feed · verified cues · calls · voices", h=80))
s.append(chip(470, 1120, 250, "League Memory", "MCP server · read-only SQL · SQLite"))
s.append(chip(950, 1120, 330, "docker build", "Studio bundle + package + services → images"))

# GitHub
s.append(boundary(1340, 985, 420, 245, "GitHub (outside Azure)", "#FAFAFB", "#C9CFD7"))
s.append(chip(1362, 1025, 376, "Repository · malikbello/matchcut", "PRs · Dependabot · CodeQL", ours=False))
s.append(
    chip(
        1362,
        1105,
        376,
        "CI checks, run before every commit",
        "format · lint · types · tests (80 % gate)",
        ours=False,
    )
)
s.append(text(1362, 1200, "Release identity: OIDC federation (no stored secrets)", 11.5, 400, MUTED))

# ---------------------------------------------------------------- flows
s.append(line([(430, 1045), (468, 1045)]))
s.append(badge(1, 449, 1027))
s.append(line([(595, 1005), (595, 950), (1318, 950), (1318, 290), (1362, 290)]))
s.append(badge(2, 595, 970))
s.append(line([(595, 1085), (595, 1118)], start=True))
s.append(badge(3, 618, 1102))
s.append(line([(720, 1045), (758, 1045)]))
s.append(line([(835, 1005), (835, 935), (1328, 935), (1328, 498), (1362, 498)]))
s.append(badge(4, 835, 970))
s.append(line([(910, 1045), (948, 1045)]))
s.append(badge(5, 929, 1027))
s.append(line([(1115, 1085), (1115, 1118)]))
s.append(line([(1115, 1186), (1115, 1243), (250, 1243), (250, 666), (336, 666)]))
s.append(badge(6, 700, 1243))
s.append(line([(510, 666), (545, 666), (545, 600), (558, 600)], "ident"))
s.append(badge(7, 527, 633))
s.append(line([(230, 228), (614, 228), (614, 260)], start=True))
s.append(badge(8, 283, 228))
s.append(line([(632, 398), (632, 714)], "async"))
s.append(badge(9, 632, 470))
s.append(line([(662, 740), (770, 740), (770, 560), (858, 560)], "async"))
s.append(badge(10, 770, 605))
s.append(line([(1282, 440), (1292, 440), (1292, 300), (1362, 300)]))
s.append(line([(1282, 470), (1292, 470), (1292, 508), (1362, 508)]))
s.append(badge(11, 1292, 455))
s.append(line([(960, 602), (960, 714)]))
s.append(badge(12, 960, 622))
s.append(line([(652, 398), (652, 714)], "async"))
s.append(badge(13, 672, 560))
s.append(line([(930, 714), (930, 667), (700, 667), (700, 400)]))
s.append(badge(14, 850, 667))
s.append(line([(396, 300), (558, 300)], "ident"))
s.append(text(400, 316, "Entra tokens (all services)", 11, 500, MUTED))

# ---------------------------------------------------------------- legend + numbered steps
LY = 1255
s.append(f'<rect x="40" y="{LY}" width="1760" height="280" rx="10" fill="#F6F7F9" stroke="#E1E5EA"/>')
s.append(text(60, LY + 30, "Main flow · a match to every fan's film", 14, 700))
steps = [
    "1  sim plays the match: events and 10 Hz tracking",
    "2  agents write each moment's line on gpt-5-mini",
    "3  the Historian asks League Memory over MCP",
    "4  calls, verified lines and audio description voiced (Speech)",
    "5  the match package: feed, verified cues, calls, voices",
    "6  images are built and pushed to the registry",
    "7  the app and job pull images with the managed identity",
    "8  fans open the Studio; api streams verified cues in time",
    "9  a moment, or Clip that: its slices go on the queue",
    "10 KEDA starts a replica per message; frames are drawn",
    "11 QA agent: Speech hears each film, gpt-5-mini reads it",
    "12 pieces, films and QA reports land in Blob",
    "13 at the whistle the Recap Factory queues every fan film",
    "14 api serves films, share pages and QR hand-over",
]
for i, st in enumerate(steps):
    col, row = divmod(i, 5)
    s.append(text(60 + col * 470, LY + 60 + row * 26, st, 12.5, 400, "#2B3240"))
s.append(
    text(
        60,
        LY + 205,
        "Code computes every number; AI writes and perceives. Every line is verified before it is voiced, and every film is checked after it is made.",
        12.5,
        600,
        "#2B3240",
    )
)
s.append(
    text(
        60,
        LY + 229,
        "The match pipeline runs before kick-off, so the show plays its verified cues on the match clock; clips, QA and fan films run on Azure as the match unfolds and at the whistle.",
        12.5,
        400,
        "#2B3240",
    )
)
s.append(text(1480, LY + 30, "Deployment", 14, 700))
s.append(text(1480, LY + 56, "deploy.sh runs Bicep: environment, app,", 12.5, 400, "#2B3240"))
s.append(text(1480, LY + 74, "job, storage, registry, identity, roles", 12.5, 400, "#2B3240"))
s.append(text(1480, LY + 110, "Lines", 14, 700))
lx = 1480
s.append(
    f'<line x1="{lx}" y1="{LY + 132}" x2="{lx + 40}" y2="{LY + 132}" stroke="{LINE}" stroke-width="1.5"/>'
    + text(lx + 50, LY + 136, "synchronous request", 12, 400, "#2B3240")
)
s.append(
    f'<line x1="{lx}" y1="{LY + 156}" x2="{lx + 40}" y2="{LY + 156}" stroke="{LINE}" stroke-width="1.5" stroke-dasharray="7 5"/>'
    + text(lx + 50, LY + 160, "asynchronous message", 12, 400, "#2B3240")
)
s.append(
    f'<line x1="{lx}" y1="{LY + 180}" x2="{lx + 40}" y2="{LY + 180}" stroke="{LINE}" stroke-width="1.5" stroke-dasharray="2 4"/>'
    + text(lx + 50, LY + 184, "identity / control plane", 12, 400, "#2B3240")
)
s.append(
    f'<rect x="{lx}" y="{LY + 198}" width="40" height="3" fill="{SIGNAL}"/>'
    + text(lx + 50, LY + 206, "Matchcut code", 12, 400, "#2B3240")
)
s.append(
    text(
        40,
        H - 10,
        "Azure architecture icons © Microsoft, used unmodified under the Azure icon terms. All clubs, players and matches are fictional.",
        11,
        400,
        MUTED,
    )
)
s.append("</svg>")
OUT.write_text("".join(s), encoding="utf-8")
print("wrote", OUT)

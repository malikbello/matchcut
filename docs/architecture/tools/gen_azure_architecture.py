"""Generate the Matchcut Azure architecture diagram (component + deployment view).

Follows the azure-architecture-diagrams skill: official Azure icons (V24, unmodified),
real boundaries, numbered flows, line legend, metadata block. Output: SVG (GitHub-safe).
Usage: python gen_azure_architecture.py <icons_dir> <out.svg>
"""

import re
import sys
from pathlib import Path

ICONS_DIR = Path(sys.argv[1])
OUT = Path(sys.argv[2])

ICON_FILES = {
    "swa": "web/01007-icon-service-Static-Apps.svg",
    "aca": "other/02884-icon-service-Worker-Container-App.svg",
    "acaenv": "other/02989-icon-service-Container-Apps-Environments.svg",
    "eh": "analytics/00039-icon-service-Event-Hubs.svg",
    "st": "storage/10086-icon-service-Storage-Accounts.svg",
    "sql": "databases/10130-icon-service-SQL-Database.svg",
    "foundry": "ai + machine learning/038470614-icon-service-Foundry-Models.svg",
    "speech": "ai + machine learning/00797-icon-service-Speech-Services.svg",
    "translator": "ai + machine learning/00800-icon-service-Translator-Text.svg",
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


def text(x, y, s, size=13, weight=400, fill=INK, anchor="start", italic=False):
    st = "font-style:italic;" if italic else ""
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" style="font:{weight} {size}px {FONT};{st}" '
        f'fill="{fill}">{s}</text>'
    )


def node(key, cx, y, title, sub=None, size=52, ours=False):
    out = [icon(key, cx - size / 2, y, size)]
    out.append(text(cx, y + size + 18, title, 13, 600, INK, "middle"))
    if sub:
        out.append(text(cx, y + size + 34, sub, 11.5, 400, MUTED, "middle"))
    if ours:
        out.append(
            f'<rect x="{cx - 22}" y="{y + size + 40}" width="44" height="3" rx="1.5" fill="{SIGNAL}"/>'
        )
    return "".join(out)


def boundary(x, y, w, h, label, fill="none", stroke="#9AA4B2", dash="", key=None, r=10):
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


def arrow(points, style="solid", num=None, num_at=None, color=LINE):
    d = "M" + " L".join(f"{px} {py}" for px, py in points)
    dash = {"solid": "", "async": ' stroke-dasharray="7 5"', "ident": ' stroke-dasharray="2 4"'}[style]
    out = [f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"{dash} marker-end="url(#ah)"/>']
    if num is not None:
        nx, ny = num_at if num_at else points[len(points) // 2]
        out.append(f'<circle cx="{nx}" cy="{ny}" r="10.5" fill="#1B1F24"/>')
        out.append(text(nx, ny + 4.2, str(num), 11.5, 700, "#FFFFFF", "middle"))
    return "".join(out)


W, H = 1840, 1500
s = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">',
    '<title id="t">Matchcut: Azure architecture (component and deployment view)</title>',
    '<desc id="d">Matchcut runs in one Azure resource group: Container Apps for the simulator, TV renderer, vision, insights, recap, API and League Memory MCP server; Container Apps Jobs for rendering and QA; Event Hubs, Storage, Azure SQL, Microsoft Foundry, Azure AI Speech and Translator; managed identity; Application Insights. GitHub Actions deploys with OIDC.</desc>',
    '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#3F4A57"/></marker></defs>',
    f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>',
]

# Header + metadata
s.append(text(40, 56, "Matchcut · Azure architecture", 26, 700))
s.append(
    text(
        40,
        82,
        "Component and deployment view · how the services connect, where they run, and the main flow from kick-off to every fan's cut",
        14,
        400,
        MUTED,
    )
)
s.append('<rect x="1460" y="30" width="340" height="66" rx="8" fill="#F6F7F9" stroke="#E1E5EA"/>')
s.append(text(1474, 52, "Version 1.0 · 17 Oct 2026 · Draft for build", 12, 600, "#3A4350"))
s.append(text(1474, 70, "Author: Malik Bello · Region: East US 2", 12, 400, MUTED))
s.append(text(1474, 88, "Related: concept diagram · ADR-001 (to be written)", 12, 400, MUTED))

# External: users
s.append(boundary(40, 130, 190, 470, "People", "#FAFAFB", "#C9CFD7"))
for i, (who, sub) in enumerate(
    [("Fans", "phone · TV · web"), ("Studio producer", "rights-holder"), ("Judges", "live demo link")]
):
    cy = 205 + i * 135
    s.append(
        f'<circle cx="135" cy="{cy}" r="15" fill="none" stroke="{INK}" stroke-width="2"/>'
        f'<path d="M108 {cy + 52} Q135 {cy + 16} 162 {cy + 52}" fill="none" stroke="{INK}" stroke-width="2"/>'
    )
    s.append(text(135, cy + 74, who, 13, 600, INK, "middle"))
    s.append(text(135, cy + 90, sub, 11.5, 400, MUTED, "middle"))

# External: GitHub
s.append(boundary(40, 860, 190, 300, "GitHub (outside Azure)", "#FAFAFB", "#C9CFD7"))
for i, (t1, t2) in enumerate(
    [
        ("Repository", "malikbello/matchcut"),
        ("GitHub Actions", "CI · tests · deploy"),
        ("Container registry", "ghcr.io images"),
    ]
):
    yy = 905 + i * 82
    s.append(f'<rect x="62" y="{yy}" width="146" height="58" rx="8" fill="#FFFFFF" stroke="#C9CFD7"/>')
    s.append(text(135, yy + 25, t1, 12.5, 600, INK, "middle"))
    s.append(text(135, yy + 43, t2, 11, 400, MUTED, "middle"))

# Azure boundaries
s.append(
    boundary(
        270, 120, 1530, 1050, "Microsoft Entra ID tenant · Default Directory", "#FBFCFD", "#B7C0CC", "6 4"
    )
)
s.append(
    boundary(
        290,
        150,
        1490,
        1000,
        "Subscription · Azure subscription 1 (Free Trial, spending limit on)",
        "none",
        "#9AA4B2",
        "",
        "sub",
    )
)
s.append(
    boundary(
        310, 185, 1450, 945, "Resource group · rg-matchcut-dev · East US 2", "#F7F9FC", "#9AA4B2", "", "rg"
    )
)


# Side-node helper: icon left, labels right
def side(key, x, y, title, sub=None, size=46, ours=False):
    out = [icon(key, x, y, size)]
    out.append(text(x + size + 12, y + size / 2 - 3, title, 13, 600))
    if sub:
        out.append(text(x + size + 12, y + size / 2 + 14, sub, 11.5, 400, MUTED))
    if ours:
        out.append(
            f'<rect x="{x + size + 12}" y="{y + size / 2 + 22}" width="36" height="3" rx="1.5" fill="{SIGNAL}"/>'
        )
    return "".join(out)


def badge(n, x, y):
    return f'<circle cx="{x}" cy="{y}" r="10.5" fill="#1B1F24"/>' + text(
        x, y + 4.2, str(n), 11.5 if len(str(n)) < 3 else 10, 700, "#FFFFFF", "middle"
    )


def line(points, style="solid", end=True):
    d = "M" + " L".join(f"{px} {py}" for px, py in points)
    dash = {"solid": "", "async": ' stroke-dasharray="7 5"', "ident": ' stroke-dasharray="2 4"'}[style]
    m = ' marker-end="url(#ah)"' if end else ""
    return f'<path d="{d}" fill="none" stroke="{LINE}" stroke-width="1.5"{dash}{m}/>'


# Left column inside RG
s.append(side("swa", 338, 238, "Static Web Apps", "web app · Free plan", ours=True))
s.append(side("mi", 338, 458, "Managed identity", "keyless · RBAC roles"))
s.append(side("appi", 338, 672, "Application Insights", "traces · metrics · logs"))
s.append(side("law", 338, 762, "Log Analytics", "workspace"))
s.append(side("cost", 338, 950, "Cost Management", "budget $5 · $10 · $25"))

# Event Hubs bus
s.append('<rect x="560" y="215" width="740" height="64" rx="10" fill="#EEF5FC" stroke="#7FA9D6"/>')
s.append(icon("eh", 572, 222, 48))
s.append(text(632, 243, "Azure Event Hubs · Standard", 13, 600))
s.append(
    text(
        632,
        262,
        "hubs: match-events · tracking · detections · cues   ·   partition key = match_id",
        11.5,
        400,
        MUTED,
    )
)

# Container Apps environment (label at the bottom so flows can enter from the top)
s.append(
    '<rect x="560" y="305" width="740" height="585" rx="10" fill="#FFFFFF" stroke="#7FA9D6" stroke-width="1.2"/>'
)
s.append(icon("acaenv", 572, 860, 18))
s.append(text(596, 874, "Container Apps environment · Consumption plan · scale to zero", 12, 600, "#3A4350"))
C1, C2, C3, C4 = 625, 795, 965, 1135
R1, R2 = 330, 515
s.append(node("aca", C1, R1, "sim", "league + match engine", ours=True))
s.append(node("aca", C2, R1, "renderer", "TV camera → HLS", ours=True))
s.append(node("aca", C3, R1, "vision", "auto-eventing", ours=True))
s.append(node("aca", C4, R1, "insights", "live agents (MAF)", ours=True))
s.append(node("aca", 710, R2, "api", "SSE · REST · auth", ours=True))
s.append(node("aca", 880, R2, "league-memory", "MCP server", ours=True))
s.append(node("aca", C4, R2, "recap", "video agents (MAF)", ours=True))
s.append(
    '<rect x="1060" y="690" width="225" height="150" rx="9" fill="#FBFCFE" stroke="#7FA9D6" stroke-dasharray="4 3"/>'
)
s.append(text(1072, 708, "Container Apps Jobs · KEDA · 0 → N", 11.5, 600, "#3A4350"))
s.append(side("aca", 1072, 718, "render-job", "frames → MP4", 40, ours=True))
s.append(side("aca", 1072, 780, "qa-job", "listen + look", 40, ours=True))

# Data stores
s.append('<rect x="560" y="925" width="320" height="140" rx="10" fill="#FFFFFF" stroke="#9AA4B2"/>')
s.append(side("sql", 590, 965, "Azure SQL Database", "free offer · Entra-only auth", 52))
s.append('<rect x="920" y="925" width="380" height="140" rx="10" fill="#FFFFFF" stroke="#9AA4B2"/>')
s.append(side("st", 950, 965, "Storage account", "Blob: hls · packages · Queue: render · qa", 52))

# AI column
s.append(boundary(1360, 215, 400, 680, "Microsoft Foundry + Azure AI services", "#FFFFFF", "#9AA4B2"))
s.append(side("foundry", 1384, 262, "Foundry Models · matchcut-ai", "gpt-5-mini · o4-mini", 52))
s.append(text(1448, 336, "evaluations · tracing · content filters", 11.5, 400, MUTED))
s.append(side("speech", 1384, 470, "Azure AI Speech", "neural TTS · speech-to-text", 52))
s.append(side("translator", 1384, 690, "Azure AI Translator", "back-translation check", 52))

# Flows
I = 26  # half icon
s.append(line([(C1, R1), (C1, 281)], "async"))
s.append(badge(1, C1 - 20, 298))
s.append(line([(C2, 279), (C2, R1 - 2)], "async"))
s.append(badge(2, C2 - 20, 298))
s.append(line([(C2 + 12, 432), (C2 + 12, 905), (950, 905), (950, 923)]))
s.append(badge(3, C2 + 12, 700))
s.append(line([(1020, 923), (1020, R1 + I), (C3 + I + 2, R1 + I)]))
s.append(badge(4, 1020, 470))
s.append(line([(C3, R1), (C3, 281)], "async"))
s.append(badge(5, C3 - 20, 298))
s.append(line([(C4 - 10, 279), (C4 - 10, R1 - 2)], "async"))
s.append(badge(6, C4 - 30, 298))
s.append(line([(C4 + 12, R1), (C4 + 12, 281)], "async"))
s.append(badge(10, C4 + 34, 298))
s.append(line([(C4 + I, R1 + I), (1318, R1 + I), (1318, 288), (1382, 288)]))
s.append(badge(7, 1240, R1 + I))
s.append(line([(C4 - I, R1 + I + 8), (1060, R1 + I + 8), (1060, R2 + I), (906 + 2, R2 + I)]))
s.append(badge(8, 1060, 450))
s.append(line([(880, 618), (880, 905), (870, 905), (870, 923)]))
s.append(badge(9, 880, 760))
s.append(line([(1210, 279), (1210, R2 + I), (C4 + I + 2, R2 + I)], "async"))
s.append(badge(11, 1210, 470))
s.append(line([(C4 + I, R2 + I + 10), (1326, R2 + I + 10), (1326, 496), (1382, 496)]))
s.append(badge(12, 1250, R2 + I + 10))
s.append(line([(1330, R2 + I + 10), (1330, 300), (1382, 300)], "solid"))
s.append(line([(1135, 618), (1135, 640), (1040, 640), (1040, 923)], "async"))
s.append(badge(13, 1040, 760))
s.append(line([(1180, 923), (1180, 842)], "async"))
s.append(badge(14, 1200, 885))
s.append(line([(1285, 800), (1340, 800), (1340, 510), (1382, 510)]))
s.append(badge(15, 1310, 800))
s.append(line([(710, 279), (710, R2 - 2)], "async"))
s.append(badge(16, 690, 470))
s.append(line([(361, 290), (361, 302), (540, 302), (540, 541), (684, 541)]))
s.append(badge(17, 610, 541))
s.append(line([(230, 262), (336, 262)]))
s.append(badge(18, 283, 262))
s.append(line([(736, 618), (736, 912), (990, 912), (990, 923)]))
s.append(badge(19, 736, 760))
s.append(line([(396, 528), (558, 528)], "ident"))
s.append(text(410, 545, "Entra tokens (all services)", 11, 500, MUTED))
s.append(line([(558, 700), (520, 700)], "async"))
s.append(text(442, 730, "OpenTelemetry", 11, 500, MUTED))
s.append(line([(230, 1015), (268, 1015)], "ident"))
s.append(badge("D1", 249, 995))
s.append(line([(230, 1097), (545, 1097), (545, 880), (558, 880)], "async"))
s.append(badge("D2", 400, 1097))

# Legend + numbered steps
LY = 1190
s.append(f'<rect x="40" y="{LY}" width="1760" height="280" rx="10" fill="#F6F7F9" stroke="#E1E5EA"/>')
s.append(text(60, LY + 30, "Main flow · kick-off to every fan's cut", 14, 700))
steps = [
    "1  sim publishes match events + 10 Hz tracking (AMQP)",
    "2  renderer consumes tracking, draws the TV feed",
    "3  renderer writes HLS segments to Blob",
    "4  vision reads frames from Blob",
    "5  vision publishes detected events",
    "6  insights consumes events + detections",
    "7  agents call Foundry models (Entra token)",
    "8  Historian calls League Memory over MCP",
    "9  MCP runs parameterised, read-only SQL",
    "10 insights publishes verified, timed cues",
    "11 recap starts at half time / full time",
    "12 recap agents call Foundry + Speech (TTS timing)",
    "13 recap enqueues one render task per fan profile",
    "14 render-job scales 0→N, writes MP4 to Blob",
    "15 qa-job: speech-to-text + vision check, then publish",
    "16 api streams cues to screens (SSE)",
    "17 web app calls api (judge access code, rate limits)",
    "18 fans open the web app",
    "19 api serves videos via short-lived SAS links",
]
for i, st in enumerate(steps):
    col, row = divmod(i, 7)
    s.append(text(60 + col * 470, LY + 60 + row * 26, st, 12.5, 400, "#2B3240"))
s.append(text(1480, LY + 30, "Deployment", 14, 700))
s.append(text(1480, LY + 60, "D1  Actions signs in with OIDC (no secrets)", 12.5, 400, "#2B3240"))
s.append(text(1480, LY + 86, "D2  Bicep/azd deploy · images from ghcr.io", 12.5, 400, "#2B3240"))
s.append(text(1480, LY + 130, "Lines", 14, 700))
lx = 1480
s.append(
    f'<line x1="{lx}" y1="{LY + 152}" x2="{lx + 40}" y2="{LY + 152}" stroke="{LINE}" stroke-width="1.5"/>'
    + text(lx + 50, LY + 156, "synchronous request", 12, 400, "#2B3240")
)
s.append(
    f'<line x1="{lx}" y1="{LY + 176}" x2="{lx + 40}" y2="{LY + 176}" stroke="{LINE}" stroke-width="1.5" stroke-dasharray="7 5"/>'
    + text(lx + 50, LY + 180, "asynchronous event / message", 12, 400, "#2B3240")
)
s.append(
    f'<line x1="{lx}" y1="{LY + 200}" x2="{lx + 40}" y2="{LY + 200}" stroke="{LINE}" stroke-width="1.5" stroke-dasharray="2 4"/>'
    + text(lx + 50, LY + 204, "identity / control plane", 12, 400, "#2B3240")
)
s.append(
    f'<rect x="{lx}" y="{LY + 218}" width="40" height="3" fill="{SIGNAL}"/>'
    + text(lx + 50, LY + 226, "Matchcut code (our containers)", 12, 400, "#2B3240")
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

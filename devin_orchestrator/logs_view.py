"""Minimal HTML viewer for the live log stream (GET /logs).

Renders a self-contained dark "terminal" page that subscribes to
``GET /logs/stream`` via ``EventSource`` and appends each line as it arrives.
Lifecycle icons are colourised client-side; auto-scroll can be paused.
"""

from __future__ import annotations

from html import escape

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Logs &middot; {repo}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #0d1117; color: #c9d1d9;
         font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  header {{ position: sticky; top: 0; display: flex; gap: 12px; align-items: center;
            padding: 10px 16px; background: #161b22; border-bottom: 1px solid #30363d; }}
  header h1 {{ font-size: 14px; margin: 0; font-weight: 600; }}
  header .repo {{ color: #8b949e; }}
  header .spacer {{ flex: 1; }}
  #status {{ font-size: 12px; padding: 2px 8px; border-radius: 999px;
             border: 1px solid #30363d; }}
  #status.on {{ color: #3fb950; border-color: #238636; }}
  #status.off {{ color: #f85149; border-color: #da3633; }}
  button {{ background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
            border-radius: 6px; padding: 4px 10px; cursor: pointer; }}
  button:hover {{ border-color: #8b949e; }}
  #log {{ margin: 0; padding: 12px 16px; white-space: pre-wrap; word-break: break-word; }}
  .line {{ display: block; }}
  .info {{ color: #58a6ff; }} .warn {{ color: #d29922; }} .err {{ color: #f85149; }}
  .muted {{ color: #6e7681; }}
</style>
</head>
<body>
<header>
  <h1>Devin Orchestrator logs</h1>
  <span class="repo">{repo}</span>
  <span class="spacer"></span>
  <span id="status" class="off">connecting&hellip;</span>
  <button id="follow">Following</button>
  <button id="clear">Clear</button>
</header>
<pre id="log"></pre>
<script>
  const log = document.getElementById('log');
  const status = document.getElementById('status');
  const followBtn = document.getElementById('follow');
  let follow = true;

  followBtn.onclick = () => {{
    follow = !follow;
    followBtn.textContent = follow ? 'Following' : 'Paused';
    if (follow) window.scrollTo(0, document.body.scrollHeight);
  }};
  document.getElementById('clear').onclick = () => {{ log.textContent = ''; }};

  function classify(text) {{
    if (/\\sWARNING\\s|\\s!\\s|ESCALAT|RETRY/.test(text)) return 'warn';
    if (/\\sERROR\\s|\\sx\\s|❌|🚨/.test(text)) return 'err';
    return 'info';
  }}

  function append(text) {{
    const el = document.createElement('span');
    el.className = 'line ' + classify(text);
    el.textContent = text;
    log.appendChild(el);
    if (follow) window.scrollTo(0, document.body.scrollHeight);
  }}

  const es = new EventSource('/logs/stream');
  es.onopen = () => {{ status.textContent = 'live'; status.className = 'on'; }};
  es.onerror = () => {{ status.textContent = 'reconnecting…'; status.className = 'off'; }};
  es.onmessage = (e) => append(e.data);
</script>
</body>
</html>
"""


def render_logs_page(repo: str) -> str:
    return _PAGE.format(repo=escape(repo))

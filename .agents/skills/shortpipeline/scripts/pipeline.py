"""Cliente local para operar a fila do ShortPipeline."""
import argparse
import json
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


def api(path, method="GET", body=None):
    payload = json.dumps(body).encode() if body is not None else None
    request = Request(BASE + path, data=payload, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def channel_settings(channel, override=None):
    cfg = api("/api/config")["channels"].get(channel)
    if cfg is None:
        raise ValueError(f"Canal desconhecido: {channel}")
    if (override or cfg.get("upload", {}).get("mode") or "manual") != "manual":
        raise ValueError("Este job pode enviar vídeo ao YouTube. Use o painel para decidir o modo de publicação.")
    return cfg


def job_path(job_id):
    return "/api/jobs/" + quote(job_id, safe="")


def summarize(job):
    jid, data = job["id"], job["data"]
    script = data.get("script") or {}
    out = {k: job.get(k) for k in ("id", "channel", "status", "stage", "error")}
    out["title"] = script.get("title") or job.get("topic")
    out["panel"] = BASE + "/#job/" + jid
    if job["status"] == "waiting_approval":
        if script:
            out["script"] = script
        if job["stage"] == "ideia":
            out["idea_options"] = data.get("idea_options")
    render_done = job["stages"].get("render", {}).get("status") in ("done", "review_pending")
    if data.get("video") and render_done:
        out["download"] = BASE + job_path(jid) + "/file/final.mp4?download=1"
    return out


def run(args):
    if args.command == "channels":
        return [{"id": key, "name": ch["name"], "review_script": bool(ch["review"].get("after", {}).get("roteiro")),
                 "publication": ch.get("upload", {}).get("mode") or "manual"}
                for key, ch in api("/api/config")["channels"].items()]
    if args.command == "create":
        if not 1 <= args.count <= 20:
            raise ValueError("A quantidade deve estar entre 1 e 20.")
        cfg = channel_settings(args.channel)
        if args.review_script and not cfg["review"].get("after", {}).get("roteiro"):
            raise ValueError("Ative a revisão após Roteiro nas configurações do canal.")
        made = api("/api/jobs", "POST", {"channel": args.channel, "kind": args.kind, "topic": args.topic,
                                         "count": args.count})
        return [{"id": jid, "panel": BASE + "/#job/" + jid} for jid in made["created"]]
    if args.command == "wait":
        deadline = time.monotonic() + args.seconds
        while True:
            jobs = [summarize(api(job_path(jid))["job"]) for jid in args.jobs]
            if all(job["status"] not in ("queued", "running") for job in jobs) or time.monotonic() >= deadline:
                return jobs
            time.sleep(min(3, max(0, deadline - time.monotonic())))

    path = job_path(args.job)
    job = api(path)["job"]
    if args.command == "status":
        return summarize(job)
    data = job["data"]
    channel_settings(job["channel"], data.get("upload_mode_override"))
    stage = job["stage"]
    if job["status"] != "waiting_approval":
        raise ValueError("Este job não está aguardando revisão.")
    if args.command == "edit-hook":
        if stage != "roteiro" or not args.text.strip() or not (data.get("script") or {}).get("scenes"):
            raise ValueError("A edição exige uma fala nova e um roteiro aguardando revisão.")
        script = data["script"]
        script["scenes"][0]["narration"] = args.text.strip()
        return api(path + "/script", "PUT", script)
    if args.command == "approve-idea":
        options = data.get("idea_options") or []
        if stage != "ideia" or not 0 <= args.index < len(options):
            raise ValueError("Selecione um índice válido das pautas em revisão.")
        return api(path + "/approve-idea", "POST", {"index": args.index, "topic": options[args.index]["topic"]})
    if stage != args.stage:
        raise ValueError(f"Etapa atual: {stage}.")
    if job["stages"].get(stage, {}).get("status") == "review_pending":
        return api(path + "/approve-stage", "POST", {"stage": stage})
    if stage == "render":
        return api(path + "/start-render", "POST")
    if stage == "revisao":
        return api(path + "/approve", "POST", {"upload_mode": "manual"})
    raise ValueError(f"Use o painel para revisar a etapa {stage}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("channels")
    create = sub.add_parser("create")
    create.add_argument("channel")
    create.add_argument("--kind", choices=("short", "animado", "long"), default="short")
    create.add_argument("--topic")
    create.add_argument("--count", type=int, default=1)
    create.add_argument("--review-script", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("job")
    wait = sub.add_parser("wait")
    wait.add_argument("jobs", nargs="+")
    wait.add_argument("--seconds", type=int, default=45)
    approve = sub.add_parser("approve")
    approve.add_argument("job")
    approve.add_argument("stage")
    idea = sub.add_parser("approve-idea")
    idea.add_argument("job")
    idea.add_argument("index", type=int)
    hook = sub.add_parser("edit-hook")
    hook.add_argument("job")
    hook.add_argument("text")
    args = parser.parse_args()
    global BASE
    BASE = f"http://127.0.0.1:{args.port}"
    try:
        print(json.dumps(run(args), ensure_ascii=False, indent=2))
    except HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

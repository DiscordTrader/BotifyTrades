"""
Agent Studio routes — dashboard, API, SSE, auth.
"""
import json
import queue
from flask import render_template, request, jsonify, Response, redirect


_runtime = None


def _get_runtime():
    global _runtime
    if _runtime is None:
        from .runtime import AgentRuntime
        _runtime = AgentRuntime()
    return _runtime


def _check_csrf():
    if request.method == "POST":
        if not request.headers.get("X-Requested-With"):
            return jsonify({"success": False, "error": "Missing X-Requested-With header"}), 403
    return None


def register_routes(app):

    @app.route('/')
    def dashboard():
        return render_template('dashboard.html')

    @app.route('/api/tasks', methods=['POST'])
    def create_task():
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        data = request.get_json()
        if not data or not data.get("description"):
            return jsonify({"success": False, "error": "Missing description"}), 400

        runtime = _get_runtime()
        result = runtime.submit_task(
            description=data["description"],
            priority=data.get("priority", "normal"),
            approval_mode=data.get("approval_mode", "review"),
            model_override=data.get("model_override"),
        )
        return jsonify({"success": True, **result})

    @app.route('/api/tasks', methods=['GET'])
    def list_tasks():
        runtime = _get_runtime()
        status = request.args.get("status")
        limit = min(int(request.args.get("limit", 20)), 100)
        tasks = runtime.task_manager.list_tasks(status=status, limit=limit)
        return jsonify({
            "success": True,
            "tasks": [t.to_dict() for t in tasks],
            "total": len(tasks),
        })

    @app.route('/api/tasks/<task_id>', methods=['GET'])
    def get_task(task_id):
        runtime = _get_runtime()
        task = runtime.task_manager.get_task(task_id)
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404

        messages = runtime.bus.get_messages(task_id)
        return jsonify({
            "success": True,
            "task": task.to_dict(),
            "messages": [m.to_dict() for m in messages],
        })

    @app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
    def cancel_task(task_id):
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        runtime = _get_runtime()
        if runtime.cancel_task(task_id):
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Cannot cancel task"}), 400

    @app.route('/api/tasks/<task_id>/approve', methods=['POST'])
    def approve_task(task_id):
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        runtime = _get_runtime()
        if runtime.approve_task(task_id):
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Task is not awaiting approval"}), 400

    @app.route('/api/tasks/<task_id>/reject', methods=['POST'])
    def reject_task(task_id):
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        data = request.get_json() or {}
        runtime = _get_runtime()
        if runtime.reject_task(task_id, data.get("reason", "")):
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Task is not awaiting approval"}), 400

    @app.route('/api/tasks/<task_id>/rollback', methods=['POST'])
    def rollback_task(task_id):
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        runtime = _get_runtime()
        result = runtime.rollback_task(task_id)
        if result.get("success"):
            return jsonify({"success": True, **result})
        return jsonify({"success": False, "error": result.get("error", "Rollback failed")}), 400

    @app.route('/api/tasks/<task_id>/feedback', methods=['POST'])
    def submit_feedback(task_id):
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        data = request.get_json() or {}
        rating = data.get("rating")
        if rating not in ("up", "down"):
            return jsonify({"success": False, "error": "Rating must be 'up' or 'down'"}), 400

        runtime = _get_runtime()
        runtime.db.save_feedback(
            task_id=task_id,
            rating=rating,
            message_id=data.get("message_id"),
            comment=data.get("comment", ""),
        )
        return jsonify({"success": True})

    @app.route('/api/tasks/<task_id>/feedback', methods=['GET'])
    def get_feedback(task_id):
        runtime = _get_runtime()
        feedback = runtime.db.get_feedback(task_id)
        return jsonify({"success": True, "feedback": feedback})

    @app.route('/api/stream')
    def event_stream():
        runtime = _get_runtime()
        task_filter = request.args.get("task_id")
        since_seq = int(request.args.get("since_sequence", 0))

        sse_queue = runtime.bus.subscribe_sse()
        if sse_queue is None:
            return jsonify({"error": "Too many SSE clients (max 5)"}), 429

        def generate():
            try:
                if task_filter and since_seq > 0:
                    missed = runtime.bus.get_messages(task_filter, since_seq)
                    for msg in missed:
                        data = json.dumps(msg.to_dict(), default=str)
                        yield f"event: {msg.message_type}\ndata: {data}\n\n"

                while True:
                    try:
                        event_data = sse_queue.get(timeout=15)
                        if task_filter:
                            if task_filter not in event_data:
                                continue
                        yield event_data
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                runtime.bus.unsubscribe_sse(sse_queue)

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive',
            }
        )

    @app.route('/api/states')
    def get_agent_states():
        runtime = _get_runtime()
        states = runtime.get_agent_states()
        return jsonify({"success": True, "agents": states})

    @app.route('/api/config', methods=['GET'])
    def get_config():
        from .config import AgentConfig
        agents = {}
        for name, identity in AgentConfig.AGENTS.items():
            agents[name] = {
                "name": identity.name,
                "display_name": identity.display_name,
                "color": identity.color,
                "model": identity.model,
                "timeout_seconds": identity.timeout_seconds,
            }
        return jsonify({
            "success": True,
            "agents": agents,
            "config": {
                "default_model": AgentConfig.DEFAULT_MODEL,
                "max_sse_clients": AgentConfig.MAX_SSE_CLIENTS,
                "default_budget_usd": AgentConfig.DEFAULT_BUDGET_USD,
                "cost_estimate": AgentConfig.estimate_task_cost(),
            },
        })

    # ── Auth Routes ──

    @app.route('/api/auth/status', methods=['GET'])
    def auth_status():
        runtime = _get_runtime()
        status = runtime.auth.get_auth_status()
        return jsonify({"success": True, **status})

    @app.route('/api/auth/method', methods=['POST'])
    def set_auth_method():
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        data = request.get_json() or {}
        method = data.get("method")
        if not method:
            return jsonify({"success": False, "error": "Missing method"}), 400

        runtime = _get_runtime()
        result = runtime.auth.set_auth_method(method)
        return jsonify(result)

    @app.route('/api/auth/api-key', methods=['POST'])
    def set_api_key():
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        data = request.get_json() or {}
        api_key = data.get("api_key", "").strip()
        if not api_key:
            return jsonify({"success": False, "error": "Missing API key"}), 400

        runtime = _get_runtime()
        result = runtime.auth.set_api_key(api_key)
        return jsonify(result)

    @app.route('/api/auth/oauth/start', methods=['POST'])
    def start_oauth():
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        runtime = _get_runtime()
        redirect_uri = request.url_root.rstrip('/') + '/api/auth/oauth/callback'
        result = runtime.auth.start_oauth_flow(redirect_uri)
        return jsonify(result)

    @app.route('/api/auth/oauth/callback')
    def oauth_callback():
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")

        if error:
            return redirect('/?auth_error=' + error)

        if not code or not state:
            return redirect('/?auth_error=missing_params')

        runtime = _get_runtime()
        result = runtime.auth.handle_oauth_callback(code, state)

        if result.get("success"):
            return redirect('/?auth=connected')
        return redirect('/?auth_error=' + (result.get("error", "oauth_failed")))

    @app.route('/api/auth/oauth/disconnect', methods=['POST'])
    def disconnect_oauth():
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        runtime = _get_runtime()
        runtime.auth.disconnect_oauth()
        return jsonify({"success": True})

    @app.route('/api/auth/oauth/credentials', methods=['POST'])
    def set_oauth_credentials():
        csrf_err = _check_csrf()
        if csrf_err:
            return csrf_err

        data = request.get_json() or {}
        client_id = data.get("client_id", "").strip()
        if not client_id:
            return jsonify({"success": False, "error": "Missing client_id"}), 400

        runtime = _get_runtime()
        result = runtime.auth.set_oauth_credentials(
            client_id=client_id,
            client_secret=data.get("client_secret", "").strip(),
        )
        return jsonify(result)

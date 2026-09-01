"""Cryptographic capability for Cloud-owned delivery commands.

The Agent can invoke the public Mae-Flow CLI, so command spelling is never an
authorization boundary.  Cloud keeps the RSA private key outside the mounted
task workspace and pins only the public key in the task state.  Every host
mutation therefore carries a short-lived, task/action/payload-bound proof.
"""

import base64
import hashlib
import hmac
import json
import stat

from .shared import os, time
from .wiring import api


PROOF_SCHEMA = "mae-flow-host-proof/1"
AUTHORITY_SCHEMA = "mae-flow-host-authority/1"
LIFECYCLE_SCHEMA = "mae-flow-host-lifecycle/2"
RECEIPT_SCHEMA = "mae-flow-host-receipt/1"
_RSA_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
# 收据现在只封摘要,恒定几百字节;上限留给"写坏了/被人塞了别的东西"。
_RECEIPT_LIMIT = 32 * 1024


def _die(message):
    api.die("delivery: " + message, 2)


def _text(value, name, limit):
    result = str(value or "").strip()
    if not result:
        _die("%s 不能为空" % name)
    if len(result) > limit:
        _die("%s 超过 %s 字符" % (name, limit))
    return result


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _secure_mode(info, expected, label):
    mode = stat.S_IMODE(info.st_mode)
    if mode != expected:
        _die("%s 权限必须是 %s，当前是 %s" % (
            label, oct(expected), oct(mode)))
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        _die("%s 不属于当前宿主进程" % label)


def _secure_directory(path, label):
    absolute = os.path.abspath(path)
    try:
        info = os.lstat(absolute)
    except OSError as exc:
        _die("无法读取%s %s: %s" % (label, absolute, exc))
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        _die("%s必须是真实目录" % label)
    if os.path.realpath(absolute) != absolute:
        _die("%s不能经过符号链接" % label)
    _secure_mode(info, 0o700, label)
    return absolute


def _secure_file(path, label, limit=32 * 1024):
    absolute = os.path.abspath(path)
    try:
        info = os.lstat(absolute)
    except OSError as exc:
        _die("无法读取%s %s: %s" % (label, absolute, exc))
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        _die("%s必须是普通文件" % label)
    if os.path.realpath(absolute) != absolute:
        _die("%s不能经过符号链接" % label)
    if info.st_size > limit:
        _die("%s过大" % label)
    _secure_mode(info, 0o600, label)
    return absolute


def _capability_root():
    """Locate the host-only trust root without trusting task state or args.

    Production repositories live at ``<data>/<task>/<repo>`` and the Cloud
    trust root at ``<data>/.host-capabilities``.  The contract fixture runs a
    repository directly as its workspace, so it uses the one-level fallback.
    If the production root exists it always wins; an Agent-created inner
    directory can therefore only cause a visible refusal, never become trust.
    """
    project = os.path.realpath(os.getcwd())
    workspace = os.path.dirname(project)
    candidates = (
        os.path.join(os.path.dirname(workspace), ".host-capabilities"),
        os.path.join(workspace, ".host-capabilities"),
    )
    for candidate in candidates:
        if os.path.lexists(candidate):
            root = _secure_directory(candidate, "宿主信任根")
            try:
                if os.path.commonpath((project, root)) == project:
                    _die("宿主信任根不能位于 Agent 工作区")
            except ValueError:
                _die("宿主信任根与任务工作区不在同一文件系统")
            return root
    _die("当前任务找不到 Cloud 宿主信任根，拒绝宿主命令")


def _bound_task_id(root):
    """Read the task identity from the host-only cwd binding."""
    project = os.path.realpath(os.getcwd())
    name = "binding-%s.json" % hashlib.sha256(
        project.encode("utf-8")).hexdigest()
    binding = _read_json_file(os.path.join(root, name), "宿主任务绑定")
    if (not isinstance(binding, dict)
            or binding.get("schema") != "mae-flow-host-binding/1"
            or binding.get("continuous_review") is not True
            or os.path.realpath(str(binding.get("cwd") or "")) != project):
        _die("宿主任务绑定损坏或与当前工作区不匹配")
    task_id = str(binding.get("task_id") or "").strip()
    if not task_id:
        _die("宿主任务绑定缺少任务身份")
    return task_id


def host_managed_continuous_review():
    """Whether an external, Agent-inaccessible capability binds this task."""
    project = os.path.realpath(os.getcwd())
    workspace = os.path.dirname(project)
    candidates = (
        os.path.join(os.path.dirname(workspace), ".host-capabilities"),
        os.path.join(workspace, ".host-capabilities"),
    )
    for candidate in candidates:
        if not os.path.lexists(candidate):
            continue
        root = _secure_directory(candidate, "宿主信任根")
        binding_name = "binding-%s.json" % hashlib.sha256(
            project.encode("utf-8")).hexdigest()
        if not os.path.lexists(os.path.join(root, binding_name)):
            return False
        task_id = _bound_task_id(root)
        name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".json"
        path = os.path.join(root, name)
        if not os.path.lexists(path):
            return False
        stored = _read_json_file(path, "宿主能力")
        authority = stored.get("authority") if isinstance(stored, dict) else None
        if (stored.get("schema") != "mae-flow-host-capability/1"
                or not isinstance(authority, dict)
                or authority.get("task_id") != task_id):
            _die("当前任务的宿主能力绑定损坏")
        return True
    return False


def _read_json_file(path, label):
    absolute = _secure_file(path, label)
    try:
        with open(absolute, "r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _die("无法读取%s %s: %s" % (label, absolute, exc))


def _proof_payload(path):
    root = _capability_root()
    # 只把**所在目录**解引用,末段保持原样:_secure_file 还要靠它识别
    # "凭据本身是软链"。原来直接拿 abspath 和 realpath 化过的 root 比,
    # 只要 <data> 经过任何一层软链就永远不相等——macOS 的 /var 就是
    # (2026-09-01 实测:一条宿主命令都过不去,报"不在信任根内")。
    absolute = os.path.join(
        os.path.realpath(os.path.dirname(os.path.abspath(path))),
        os.path.basename(path))
    if os.path.dirname(absolute) != root:
        _die("宿主凭据不在 Cloud 宿主信任根内")
    value = _read_json_file(absolute, "宿主凭据")
    if not isinstance(value, dict) or value.get("schema") != PROOF_SCHEMA:
        _die("宿主凭据 schema 必须是 %s" % PROOF_SCHEMA)
    nonce = _text(value.get("nonce"), "proof.nonce", 200)
    if os.path.basename(absolute) != "proof-%s.json" % nonce:
        _die("宿主凭据文件名与 nonce 不匹配")
    return value, root


def _b64url(value):
    encoded = str(value or "").encode("ascii")
    return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))


def _verify_rsa_sha256(authority, message, signature):
    try:
        modulus = int.from_bytes(_b64url(authority.get("n")), "big")
        exponent = int.from_bytes(_b64url(authority.get("e")), "big")
        signed = int.from_bytes(_b64url(signature), "big")
        if modulus <= 0 or exponent <= 0 or signed >= modulus:
            return False
        size = (modulus.bit_length() + 7) // 8
        encoded = pow(signed, exponent, modulus).to_bytes(size, "big")
    except (TypeError, ValueError, OverflowError):
        return False
    digest_info = _RSA_SHA256_PREFIX + hashlib.sha256(message).digest()
    if len(encoded) < len(digest_info) + 11 or not encoded.startswith(b"\x00\x01"):
        return False
    separator = encoded.find(b"\x00", 2)
    if separator < 10 or any(value != 0xff for value in encoded[2:separator]):
        return False
    return hmac.compare_digest(encoded[separator + 1:], digest_info)


def _trusted_authority(state, proof, root):
    task_id = _text(proof.get("task_id"), "proof.task_id", 200)
    if task_id != _bound_task_id(root):
        _die("宿主凭据与当前任务目录绑定不匹配")
    name = hashlib.sha256(task_id.encode("utf-8")).hexdigest() + ".json"
    stored = _read_json_file(os.path.join(root, name), "宿主能力")
    if not isinstance(stored, dict) or stored.get("schema") != \
            "mae-flow-host-capability/1":
        _die("宿主能力文件格式损坏")
    authority = stored.get("authority")
    if not isinstance(authority, dict) or authority.get("schema") != \
            AUTHORITY_SCHEMA or authority.get("alg") != "RS256":
        _die("宿主能力没有有效的 RS256 公钥")
    if str(authority.get("task_id") or "") != task_id:
        _die("宿主能力绑定的任务不匹配")
    try:
        modulus = int.from_bytes(_b64url(authority.get("n")), "big")
        exponent = int.from_bytes(_b64url(authority.get("e")), "big")
    except (TypeError, ValueError, UnicodeError):
        _die("宿主能力公钥编码无效")
    if modulus.bit_length() < 2048 or exponent != 65537:
        _die("宿主能力公钥必须是 2048 位以上 RSA 且 e=65537")
    expected_key_id = hashlib.sha256((
        "%s.%s" % (authority.get("n"), authority.get("e"))
    ).encode("utf-8")).hexdigest()[:24]
    if not hmac.compare_digest(str(authority.get("key_id") or ""),
                               expected_key_id):
        _die("宿主能力 key_id 与公钥不匹配")
    # Agent 可写状态中的 host_authority 只是诊断镜像，不是信任根。真正的
    # 任务身份、公钥和强制模式全部来自工作区外的 capability 文件。
    return authority


def verify_host_proof(state, proof_path, action, payload):
    proof, root = _proof_payload(proof_path)
    authority = _trusted_authority(state, proof, root)
    unsigned = {
        "schema": PROOF_SCHEMA,
        "task_id": _text(proof.get("task_id"), "proof.task_id", 200),
        "action": _text(proof.get("action"), "proof.action", 40),
        "payload_digest": _text(
            proof.get("payload_digest"), "proof.payload_digest", 128),
        "nonce": _text(proof.get("nonce"), "proof.nonce", 200),
        "issued_at": int(proof.get("issued_at") or 0),
    }
    if unsigned["task_id"] != str(authority.get("task_id") or ""):
        _die("宿主凭据绑定的任务不匹配")
    if unsigned["action"] != action:
        _die("宿主凭据绑定的动作不匹配")
    expected = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    if not hmac.compare_digest(unsigned["payload_digest"], expected):
        _die("宿主凭据绑定的载荷摘要不匹配")
    now = int(time.time())
    if unsigned["issued_at"] < now - 120 or unsigned["issued_at"] > now + 30:
        _die("宿主凭据已过期或时间异常")
    if unsigned["nonce"] in state.setdefault("host_capability_nonces", []):
        _die("宿主凭据已经消费，拒绝重放")
    signature = _text(proof.get("signature"), "proof.signature", 8192)
    if authority.get("alg") != "RS256" or not _verify_rsa_sha256(
            authority, _canonical(unsigned).encode("utf-8"), signature):
        _die("宿主凭据签名无效")
    return {
        "root": root,
        "proof": {**unsigned, "signature": signature},
        "payload": payload,
    }


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def external_facts(state):
    """The one normalization both writer and verifier must share."""
    return ((state.get("quality") or {}).get("external_verification")) or {}


def _active_batch(loop):
    if not isinstance(loop, dict):
        return None
    active_id = str(loop.get("active_batch_id") or "")
    if not active_id:
        return None
    return next((item for item in loop.get("batches", [])
                 if isinstance(item, dict)
                 and str(item.get("batch_id") or "") == active_id), None)


def host_projection(state, action, payload):
    """Seal the complete lifecycle produced by one host mutation.

    A receipt for only ``PASS`` or ``results`` can be spliced together with an
    Agent-written ``current``/``status``.  Every host action therefore seals the
    same indivisible lifecycle projection; later legitimate host actions simply
    emit a newer complete projection.

    2026-09-01 勘误:投影原来把**整份 delivery_loop 与逐条意见正文**封进
    收据。写盘不限体积、读回限 32 KiB,一轮 12 条 350 字的 MR 检视(内核
    自己允许单条 4000 字)就越线;之后 feedback-open / feedback-result /
    pipeline record 乃至 MR 合入后的 close 全部永久失败,而且**制造死锁
    的那条命令自己报成功**,没有任何命令能救回来(实测复现)。改封摘要:
    防篡改强度一个字节没松,体积从此恒定。
    """
    if action not in ("feedback-open", "feedback-result", "close",
                      "pipeline-record", "intervention-reconcile"):
        return None
    loop = state.get("delivery_loop")
    loop = loop if isinstance(loop, dict) else None
    return {
        "schema": LIFECYCLE_SCHEMA,
        "action": action,
        "current": state.get("current"),
        "active_batch_id": (loop or {}).get("active_batch_id") if loop else None,
        "delivery_loop_digest": _digest(loop),
        "active_batch_digest": _digest(_active_batch(loop)),
        "external_verification_digest": _digest(external_facts(state)),
        "user_intervention_digest": _digest(state.get("user_intervention")),
    }


def _receipt_prefix(task_id):
    """Receipts belong to (task, workspace), not to a bare task id.

    信任根是按部署共享的目录:同一个任务号在另一份代码仓里(重建、
    夹具、诊断克隆)会读到不属于它的历史收据,于是"生命周期投影对不上"
    ——一单被另一单的陈账挡死。把工作区一起算进归属,串味从此不可能。
    """
    identity = "%s\0%s" % (task_id, os.path.realpath(os.getcwd()))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".receipt-"


def _receipt_path(root, task_id, nonce):
    if not all(char.isalnum() or char in "-_" for char in nonce):
        _die("宿主凭据 nonce 格式不合法")
    return os.path.join(root, "%s%s.json" % (_receipt_prefix(task_id), nonce))


def _stage_receipt(context, projection):
    """Durably stage the receipt **before** the state it seals is saved.

    2026-09-01 勘误:原来是先 save_state 再落收据。中间失败一次就留下
    "状态已推进、收据不存在"的账,而所有 trusted_* 都要求存在收据——
    宿主从此被自己锁在门外。现在先把收据 fsync 到同目录临时文件,
    状态存住了才原子改名;存不住就把临时文件删掉,不留孤儿收据
    (孤儿收据会给 Agent 伪造状态提供现成背书)。
    """
    proof = context["proof"]
    path = _receipt_path(context["root"], proof["task_id"], proof["nonce"])
    record = {
        "schema": RECEIPT_SCHEMA,
        "proof": proof,
        "payload": context["payload"],
        "projection": projection,
        "projection_digest": _digest(projection),
        "recorded_at": int(time.time()),
    }
    staged = path + ".staged"
    try:
        descriptor = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(_canonical(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        _die("无法落盘宿主权威收据: %s" % exc)
    return staged, path


def _readable_receipt(path):
    """Read one historical receipt, or ``None`` when it cannot be trusted.

    2026-09-01 勘误:这三个扫描函数原来对每一份历史收据都走严格
    _read_json_file,权限被动过、体积超限、写坏了任何一条都会 SystemExit
    掀掉整条宿主命令——反馈、流水线登记、连 MR 合入后的 close 一起永久
    失败,且无命令可救。鉴权仍旧 fail-closed(签名、载荷摘要、投影逐字
    比对一个都没松);松掉的只是"读不动的旧文件跳过去接着找"。
    """
    try:
        absolute = os.path.abspath(path)
        info = os.lstat(absolute)
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                or os.path.realpath(absolute) != absolute
                or info.st_size > _RECEIPT_LIMIT
                or stat.S_IMODE(info.st_mode) != 0o600
                or (hasattr(os, "getuid") and info.st_uid != os.getuid())):
            return None
        with open(absolute, "r", encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _scan_receipts(state):
    """Yield every readable receipt of the bound task, newest name first.

    The authority is resolved once: it is the same public key for every receipt
    of one task, and hoisting it keeps the per-record loop incapable of dying.
    """
    root = _capability_root()
    task_id = _bound_task_id(root)
    authority = _trusted_authority(state, {"task_id": task_id}, root)
    prefix = _receipt_prefix(task_id)
    try:
        names = sorted(os.listdir(root))
    except OSError as exc:
        _die("无法读取 Cloud 宿主信任根: %s" % exc)
    for name in reversed(names):
        if not name.startswith(prefix) or not name.endswith(".json"):
            continue
        record = _readable_receipt(os.path.join(root, name))
        if record is not None:
            yield authority, record


def _valid_stored_receipt(authority, record, action, projection):
    if record.get("schema") != RECEIPT_SCHEMA:
        return False
    proof = record.get("proof")
    payload = record.get("payload")
    if not isinstance(proof, dict) or proof.get("action") != action:
        return False
    if str(proof.get("task_id") or "") != str(authority.get("task_id") or ""):
        return False
    unsigned = {key: proof.get(key) for key in (
        "schema", "task_id", "action", "payload_digest", "nonce", "issued_at")}
    signature = str(proof.get("signature") or "")
    if (unsigned.get("schema") != PROOF_SCHEMA
            or not _verify_rsa_sha256(
                authority, _canonical(unsigned).encode("utf-8"), signature)):
        return False
    return (hmac.compare_digest(str(unsigned.get("payload_digest") or ""),
                                _digest(payload))
            and hmac.compare_digest(str(record.get("projection_digest") or ""),
                                    _digest(projection))
            and hmac.compare_digest(
                _canonical(record.get("projection")).encode("utf-8"),
                _canonical(projection).encode("utf-8")))


def trusted_projection(state, action, projection):
    """Verify a state projection against a host-only durable receipt."""
    for authority, record in _scan_receipts(state):
        if _valid_stored_receipt(authority, record, action, projection):
            return True
    return False


def has_receipt_for(state, action):
    """Whether this task ever produced a valid receipt for one host action."""
    for authority, record in _scan_receipts(state):
        proof = record.get("proof")
        stored = record.get("projection")
        if (isinstance(proof, dict) and proof.get("action") == action
                and isinstance(stored, dict)
                and _valid_stored_receipt(authority, record, action, stored)):
            return True
    return False


def has_host_receipt(state):
    """Whether this task has ever produced a host receipt at all.

    第一条宿主动作必须有权开链。收据落在 Agent 够不着的信任根里
    (0600、工作区之外),"一份都没有"只可能是"这个任务还没发生过宿主
    动作"——老任务升级、迁移前的现场、刚建的任务——不可能是 Agent 把
    它们删干净了。要求"开链之前先有链"只会把宿主自己锁在门外:反馈
    永远打不开,而且没有任何命令能补开第一环。
    """
    for _authority, _record in _scan_receipts(state):
        return True
    return False


def trusted_current_lifecycle(state, actions):
    """Require an exact signed predecessor before another host transition."""
    return any(trusted_projection(
        state, action, host_projection(state, action, {}))
        for action in actions)


def trusted_pipeline_projection(state, projection):
    """Verify the exact pipeline fact inside an authentic pipeline receipt.

    Later feedback legitimately changes ``current`` and ``delivery_loop``. The
    original pipeline receipt remains authoritative for its immutable quality
    projection, while ready/terminal attestations still require a separate
    full-lifecycle receipt for their current state.
    """
    wanted = _digest(projection or {})
    for authority, record in _scan_receipts(state):
        stored = record.get("projection")
        if (isinstance(stored, dict)
                and hmac.compare_digest(
                    str(stored.get("external_verification_digest") or ""), wanted)
                and _valid_stored_receipt(
                    authority, record, "pipeline-record", stored)):
            return True
    return False


def trusted_active_batch(state, actions):
    """Verify active_batch_id and the complete active batch against a receipt.

    Agent work may legitimately move ``current`` between host calls, but it may
    not rewrite which feedback owns the writer or any field of that batch.
    """
    loop = state.get("delivery_loop") or {}
    active_id = str(loop.get("active_batch_id") or "")
    active = _active_batch(loop)
    if not active_id or active is None:
        return False
    wanted = _digest(active)
    for authority, record in _scan_receipts(state):
        stored = record.get("projection")
        if not isinstance(stored, dict):
            continue
        proof = record.get("proof")
        action = str((proof or {}).get("action") or "") \
            if isinstance(proof, dict) else ""
        if (action in actions
                and stored.get("active_batch_id") == active_id
                and hmac.compare_digest(
                    str(stored.get("active_batch_digest") or ""), wanted)
                and _valid_stored_receipt(authority, record, action, stored)):
            return True
    return False


def save_with_host_proof(state, context):
    nonce = context["proof"]["nonce"]
    consumed = state.setdefault("host_capability_nonces", [])
    consumed.append(nonce)
    # Proofs expire in two minutes. A bounded replay window is sufficient and
    # prevents the task state growing forever during a long-lived MR.
    if len(consumed) > 256:
        del consumed[:-256]
    projection = host_projection(
        state, context["proof"]["action"], context["payload"])
    if projection is None:
        _die("宿主命令没有形成可核对的权威投影")
    staged, path = _stage_receipt(context, projection)
    try:
        api.save_state(state)
    except BaseException:
        try:
            os.unlink(staged)
        except OSError:
            pass
        raise
    try:
        os.rename(staged, path)
    except OSError as exc:
        _die("无法落盘宿主权威收据: %s" % exc)

from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
import os
from datetime import datetime
from pathlib import Path

# --- Config básica ---
app = Flask(__name__)

# Ruta absoluta a torneo.db (funciona en Windows y en PythonAnywhere)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "torneo.db"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH.as_posix()}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

db = SQLAlchemy(app)

# --- bootstrap de esquema: añade 'active' si falta (SQLite) ---
with app.app_context():
    from sqlalchemy import inspect, text
    insp = inspect(db.engine)
    cols = [c["name"] for c in insp.get_columns("player")]
    if "active" not in cols:
        db.session.execute(text("ALTER TABLE player ADD COLUMN active BOOLEAN NOT NULL DEFAULT 1"))
        db.session.commit()

# ---------- MODELOS ----------
class Player(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)

class RoundInfo(db.Model):
    """Información por ronda (por ahora, solo 'descanso')."""
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    bye_player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=True)
    bye_player = db.relationship("Player", foreign_keys=[bye_player_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Game(db.Model):
    """Partida/mesa."""
    id = db.Column(db.Integer, primary_key=True)
    round_number = db.Column(db.Integer, nullable=False)
    table_no = db.Column(db.Integer, nullable=False)
    banned_card = db.Column(db.String, nullable=True)
    sweep = db.Column(db.Boolean, default=False)  # barrida: solo el 1º puntúa (3)
    save_player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=True)
    save_player = db.relationship("Player", foreign_keys=[save_player_id])
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GameResult(db.Model):
    """Resultado por jugador en una partida."""
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("game.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("player.id"), nullable=False)
    position = db.Column(db.Integer, nullable=True)  # 1=ganador, 2=segundo, 3=tercero; None si sin posición
    game = db.relationship("Game", backref=db.backref("results", lazy=True, cascade="all, delete-orphan"))
    player = db.relationship("Player")

# ---------- REGLAS DE PUNTUACIÓN ----------
def points_for_position(position: int, sweep: bool) -> int:
    if position is None:
        return 0
    if sweep:
        return 3 if position == 1 else 0
    if position == 1:
        return 3
    if position == 2:
        return 2
    if position == 3:
        return 1
    return 0

# ---------- SEED JUGADORES ----------
def seed_players():
    names = ["Borux", "Negro", "Gueta", "Teran", "Mauro", "Gordor", "Xephi", "Omar", "Richard"]
    for n in names:
        if not Player.query.filter_by(name=n).first():
            db.session.add(Player(name=n))
    db.session.commit()

# ---------- IMPORTADOR DE TUS RONDAS ----------
NAME_FIX = {
    "Goldor": "Gordor",
    "Xephy": "Xephi",
}

def get_or_create_player(name: str) -> Player:
    norm = NAME_FIX.get(name, name)
    p = Player.query.filter_by(name=norm).first()
    if p:
        return p
    # si no existe el normalizado, intenta con el original
    p = Player.query.filter_by(name=name).first()
    if p:
        return p
    p = Player(name=norm)
    db.session.add(p)
    db.session.flush()
    return p

def add_game(round_no, table_no, players, winner=None, second=None, third=None, banned=None, bye=None):
    """Crea RoundInfo (si bye), Game y GameResult. second/third pueden ser None."""
    # RoundInfo (bye)
    ri = RoundInfo.query.filter_by(number=round_no).first()
    if not ri:
        ri = RoundInfo(number=round_no)
        db.session.add(ri)
        db.session.flush()
    if bye:
        ri.bye_player_id = get_or_create_player(bye).id

    g = Game(round_number=round_no, table_no=table_no, banned_card=banned or None)
    # 'sweep' si hay ganador y NO hay segundo ni tercero
    g.sweep = bool(winner and (second is None) and (third is None))
    db.session.add(g)
    db.session.flush()

    # posiciones
    positions = {}
    if winner: positions[winner] = 1
    if second: positions[second] = 2
    if third:  positions[third]  = 3

    for name in players:
        pid = get_or_create_player(name).id
        pos = positions.get(name)
        db.session.add(GameResult(game_id=g.id, player_id=pid, position=pos))

def import_initial_rounds():
    """Importa tus 9 rondas tal como las pasaste. Se ejecuta una sola vez si no hay partidas."""
    if Game.query.count() > 0:
        return  # ya importado o ya hay partidas

    # RONDA 1
    add_game(1, 1, ["Negro","Mauro","Xephy","Omar"], winner="Negro", second="Omar",
             banned="Mondrak, Glory Dominus", bye="Goldor")
    add_game(1, 2, ["Richard","Gueta","Teran","Borux"], winner="Gueta",
             banned="Conduit of Worlds")

    # RONDA 2
    add_game(2, 1, ["Negro","Xephy","Richard","Gueta"], bye="Mauro")  # sin resultados aún
    add_game(2, 2, ["Omar","Borux","Goldor","Teran"], winner="Goldor", second="Teran", third="Omar",
             banned="Kotori, Pilot Prodigy")

    # RONDA 3
    add_game(3, 1, ["Negro","Mauro","Borux","Goldor"], winner="Negro", second="Borux", third="Goldor",
             banned="Peregrim took", bye="Xephy")
    add_game(3, 2, ["Omar","Richard","Gueta","Teran"])  # sin resultados

    # RONDA 4
    add_game(4, 1, ["Negro","Gueta","Richard","Borux"], winner="Gueta", second="Borux", third="Richard",
             banned="Bastion of Remembrance", bye="Omar")
    add_game(4, 2, ["Mauro","Xephy","Goldor","Teran"])  # sin resultados

    # RONDA 5
    add_game(5, 1, ["Negro","Omar","Borux","Goldor"], bye="Richard")
    add_game(5, 2, ["Mauro","Xephy","Gueta","Teran"])

    # RONDA 6
    add_game(6, 1, ["Gueta","Xephy","Richard","Goldor"], bye="Negro")
    add_game(6, 2, ["Mauro","Omar","Borux","Teran"])

    # RONDA 7
    add_game(7, 1, ["Negro","Xephy","Omar","Borux"], bye="Teran")
    add_game(7, 2, ["Mauro","Richard","Gueta","Goldor"])

    # RONDA 8
    add_game(8, 1, ["Negro","Mauro","Gueta","Teran"], bye="Borux")
    add_game(8, 2, ["Xephy","Omar","Richard","Goldor"])

    # RONDA 9
    add_game(9, 1, ["Goldor","Mauro","Omar","Richard"], bye="Gueta")
    add_game(9, 2, ["Xephy","Negro","Teran","Borux"], winner="Teran", second="Borux", third="Xephy",
             banned="Ureni of the Unwriten")

    db.session.commit()

# ---------- CLASIFICACIÓN ----------
@app.route("/")
def index():
    players = Player.query.filter_by(active=True).order_by(Player.name.asc()).all()

    # Totales (medallero + salvavidas)
    totals = {
        p.id: {"name": p.name, "points": 0, "wins": 0, "seconds": 0, "thirds": 0, "saves": 0}
        for p in players
    }

    from collections import defaultdict
    played_rounds = defaultdict(set)    # player_id -> rondas YA jugadas (mesa con ganador o barrida)
    rests_by_player = defaultdict(int)  # descansos asignados
    all_rounds = set()                  # rondas planificadas (por Game o RoundInfo)

    # Descansos (planificados)
    for ri in RoundInfo.query.all():
        all_rounds.add(ri.number)
        if ri.bye_player_id:
            rests_by_player[ri.bye_player_id] += 1

    # Mesas
    games = Game.query.order_by(Game.round_number.asc(), Game.table_no.asc()).all()
    for g in games:
        all_rounds.add(g.round_number)

        # Salvavidas: +1 punto y +1 contador
        if g.save_player_id and g.save_player_id in totals:
            totals[g.save_player_id]["points"] += 1
            totals[g.save_player_id]["saves"] += 1

        # ¿Mesa con ganador? (pos=1 o barrida)
        has_winner = any(r.position == 1 for r in g.results) or bool(g.sweep)

        # Pódium y jugadas
        for r in g.results:
            pts = points_for_position(r.position, g.sweep)
            totals[r.player_id]["points"] += pts
            if r.position == 1:
                totals[r.player_id]["wins"] += 1
            elif r.position == 2:
                totals[r.player_id]["seconds"] += 1
            elif r.position == 3:
                totals[r.player_id]["thirds"] += 1
            # Si la mesa tiene ganador, cuenta como jugada
            if has_winner:
                played_rounds[r.player_id].add(g.round_number)

    total_rounds = len(all_rounds)

    # Participación y límites de puntos
    per_player = {}
    for p in players:
        played = len(played_rounds[p.id])
        rests = rests_by_player[p.id]
        planned_to_play = max(total_rounds - rests, 0)    # partidas que le corresponden
        remaining = max(planned_to_play - played, 0)      # le faltan por jugar
        lb = totals[p.id]["points"]                       # mínimo: lo que ya tiene
        ub = lb + 4 * remaining                           # máximo: 4 por partida restante

        per_player[p.id] = {
            "name": p.name,
            "points": totals[p.id]["points"],
            "wins": totals[p.id]["wins"],
            "seconds": totals[p.id]["seconds"],
            "thirds": totals[p.id]["thirds"],
            "saves": totals[p.id]["saves"],
            "played": played,
            "rests": rests,
            "planned_to_play": planned_to_play,
            "remaining": remaining,
            "lb": lb,
            "ub": ub,
        }

    # Etiquetas de CLASIFICADO / ELIMINADO (criterio conservador por puntos)
    ids = list(per_player.keys())
    for pid in ids:
        me = per_player[pid]
        # rivales
        rival_LBs = sorted([per_player[q]["lb"] for q in ids if q != pid], reverse=True)
        rival_UBs = sorted([per_player[q]["ub"] for q in ids if q != pid], reverse=True)
        # 4º mejor rival (índice 3)
        fourth_best_rival_LB = rival_LBs[3]
        fourth_best_rival_UB = rival_UBs[3]

        status = None
        # Clinched: ni en el peor caso puede caer del top-4
        if me["lb"] > fourth_best_rival_UB:
            status = "CLASIFICADO"
        # Eliminado: ni en el mejor caso puede alcanzar el top-4
        elif me["ub"] < fourth_best_rival_LB:
            status = "ELIMINADO"

        me["status"] = status

    # Construye tabla principal (orden medallero: puntos → 1º → 2º → 3º → nombre)
    table = []
    for pid, row in per_player.items():
        table.append({
            "id": pid,
            "name": row["name"],
            "points": row["points"],
            "wins": row["wins"],
            "seconds": row["seconds"],
            "thirds": row["thirds"],
            "saves": row["saves"],
            "status": row["status"],
        })

    table.sort(key=lambda x: x["name"])
    table.sort(key=lambda x: (x["points"], x["wins"], x["seconds"], x["thirds"]), reverse=True)

    # Posición (empatada si coinciden todos los criterios)
    last_key = None
    current_pos = 0
    for i, t in enumerate(table, start=1):
        key = (t["points"], t["wins"], t["seconds"], t["thirds"])
        if key != last_key:
            current_pos = i
            last_key = key
        t["pos"] = current_pos

    # Sección de participación para mostrar jugadas/pedientes
    participation = []
    for pid in ids:
        r = per_player[pid]
        participation.append({
            "name": r["name"],
            "played": r["played"],
            "remaining": r["remaining"],
            "rests": r["rests"],
            "planned_to_play": r["planned_to_play"],
        })
    participation.sort(key=lambda x: x["name"])

    return render_template(
        "index.html",
        table=table,
        participation=participation,
        total_rounds=total_rounds,
        is_admin=session.get("is_admin", False)
    )

# ---------- PÁGINA DE RONDAS ----------
@app.route("/rounds")
def rounds_view():
    players_all = Player.query.filter_by(active=True).order_by(Player.name.asc()).all()
    bye_by_round = {ri.number: (ri.bye_player.name if ri.bye_player else None,
                                ri.bye_player_id if ri.bye_player_id else None)
                    for ri in RoundInfo.query.all()}

    rounds = {}
    games = Game.query.order_by(Game.round_number.asc(), Game.table_no.asc()).all()
    for g in games:
        participants = []
        for r in sorted(g.results, key=lambda x: (x.position or 9999)):
            participants.append({"name": r.player.name, "pos": r.position})

        winner = next((r.player.name for r in g.results if r.position == 1), None)
        second = next((r.player.name for r in g.results if r.position == 2), None)
        third  = next((r.player.name for r in g.results if r.position == 3), None)

        # ¿Esta mesa tiene ganador? (cualquier r.position==1 o g.sweep marcado)
        has_winner = any(r.position == 1 for r in g.results) or bool(g.sweep)

        bye_name, bye_id = bye_by_round.get(g.round_number, (None, None))
        rounds.setdefault(g.round_number, {"bye": bye_name, "bye_id": bye_id, "games": []})
        rounds[g.round_number]["games"].append({
            "id": g.id,
            "table": g.table_no,
            "participants": participants,
            "winner": winner,
            "second": second,
            "third": third,
            "banned": g.banned_card,
            "sweep": g.sweep,
            "save": (g.save_player.name if g.save_player else None),  # Salvavidas
            "played": has_winner
        })

    ordered = []
    for number in sorted(rounds.keys()):
        r = rounds[number]
        r["games"].sort(key=lambda x: x["table"])
        ordered.append({"number": number, "bye": r["bye"], "bye_id": r["bye_id"], "games": r["games"]})

    return render_template("rounds.html",
                           rounds=ordered,
                           players_all=players_all,
                           is_admin=session.get("is_admin", False))

@app.route("/rounds/<int:round_no>/bye", methods=["POST"])
def round_set_bye(round_no):
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    bye_pid = request.form.get("bye_player_id")
    bye_pid = int(bye_pid) if bye_pid and bye_pid != "none" else None

    ri = RoundInfo.query.filter_by(number=round_no).first()
    if not ri:
        ri = RoundInfo(number=round_no)
        db.session.add(ri)
    ri.bye_player_id = bye_pid
    db.session.commit()
    flash(f"Descanso de la ronda {round_no} actualizado.", "success")
    return redirect(url_for("rounds_view"))

@app.route("/games/<int:game_id>/edit", methods=["GET", "POST"])
def game_edit(game_id):
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("index"))

    g = Game.query.get_or_404(game_id)
    # Participantes = los que tienen GameResult en esa mesa
    results = GameResult.query.filter_by(game_id=game_id).all()
    participant_ids = [r.player_id for r in results]
    participants = Player.query.filter(Player.id.in_(participant_ids)).order_by(Player.name.asc()).all()
    all_players = Player.query.order_by(Player.name.asc()).all()

    if request.method == "POST":
        # Leer formulario
        banned = (request.form.get("banned_card") or "").strip() or None
        sweep = (request.form.get("sweep") == "on")
        save_player_id = request.form.get("save_player_id")
        save_player_id = int(save_player_id) if save_player_id and save_player_id != "none" else None

        # Selecciones de ganador/segundo/tercero (por id)
        def parse_pid(key):
            v = request.form.get(key)
            return int(v) if v and v != "none" else None

        winner_id = parse_pid("winner_id")
        second_id = parse_pid("second_id")
        third_id  = parse_pid("third_id")

        # Validaciones
        if winner_id is None or winner_id not in participant_ids:
            flash("Debes elegir un ganador que participe en la mesa.", "warning")
            return redirect(url_for("game_edit", game_id=game_id))

        if sweep:
            # En barrida, solo el ganador puntúa, resto sin posición.
            second_id = None
            third_id = None
        else:
            # En normal: no se permiten duplicados, y si hay second/third deben ser participantes distintos
            chosen = [pid for pid in [winner_id, second_id, third_id] if pid]
            if len(set(chosen)) != len(chosen):
                flash("Ganador, segundo y tercero no pueden repetirse.", "warning")
                return redirect(url_for("game_edit", game_id=game_id))
            for pid in [second_id, third_id]:
                if pid is not None and pid not in participant_ids:
                    flash("Segundo/Tercero deben estar en la mesa.", "warning")
                    return redirect(url_for("game_edit", game_id=game_id))

        if save_player_id and save_player_id not in participant_ids:
            flash("El 'salvavidas' debe estar en la mesa.", "warning")
            return redirect(url_for("game_edit", game_id=game_id))

        # Guardar en DB
        g.banned_card = banned
        g.sweep = sweep
        g.save_player_id = save_player_id

        # Reinicia posiciones
        for r in results:
            r.position = None

        # Asigna posiciones
        for r in results:
            if r.player_id == winner_id:
                r.position = 1
        if not sweep:
            for r in results:
                if second_id and r.player_id == second_id:
                    r.position = 2
                if third_id and r.player_id == third_id:
                    r.position = 3

        db.session.commit()
        flash("Partida actualizada.", "success")
        return redirect(url_for("rounds_view"))

    # GET: Datos actuales para el formulario
    current = {r.player_id: r.position for r in results}
    context = {
        "game": g,
        "participants": participants,
        "all_players": all_players,
        "current": current,
        "is_admin": True,
    }
    return render_template("game_edit.html", **context)

# === Acciones sobre mesas (admin) === Limpiar, borrar, limpiar ronda, reiniciar torneo

@app.route("/games/<int:game_id>/reset", methods=["POST"])
def game_reset(game_id):
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    g = Game.query.get_or_404(game_id)

    # Limpiar campos de la partida
    g.banned_card = None
    g.sweep = False
    g.save_player_id = None

    # Poner posiciones en blanco (None) para todos los participantes
    for r in g.results:
        r.position = None

    db.session.commit()
    flash(f"Ronda {g.round_number} Mesa {g.table_no} vaciada.", "success")
    return redirect(url_for("rounds_view"))


@app.route("/games/<int:game_id>/delete", methods=["POST"])
def game_delete(game_id):
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    g = Game.query.get_or_404(game_id)
    rn, tn = g.round_number, g.table_no
    # Al borrar Game, sus GameResult se eliminan por el cascade="all, delete-orphan"
    db.session.delete(g)
    db.session.commit()
    flash(f"Ronda {rn} Mesa {tn} eliminada.", "success")
    return redirect(url_for("rounds_view"))


@app.route("/rounds/<int:round_no>/clear", methods=["POST"])
def round_clear(round_no):
    """Vacía ambas mesas de la ronda (si existen) y mantiene el descanso."""
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    games = Game.query.filter_by(round_number=round_no).all()
    for g in games:
        g.banned_card = None
        g.sweep = False
        g.save_player_id = None
        for r in g.results:
            r.position = None
    db.session.commit()
    flash(f"Ronda {round_no}: mesas vaciadas (se mantiene el descanso).", "success")
    return redirect(url_for("rounds_view"))


@app.route("/admin/reset_tournament", methods=["POST"])
def reset_tournament():
    """Elimina todas las rondas y mesas, manteniendo los jugadores."""
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    # Borrar via ORM para respetar cascade en Game.results
    for g in Game.query.all():
        db.session.delete(g)
    for ri in RoundInfo.query.all():
        db.session.delete(ri)
    db.session.commit()
    flash("Torneo reiniciado: se borraron todas las mesas y descansos. Jugadores conservados.", "warning")
    return redirect(url_for("rounds_view"))

# ========== ADMIN: Gestión de jugadores ==========

@app.route("/admin/players")
def players_admin():
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("index"))

    from sqlalchemy import func
    q_counts = (db.session.query(GameResult.player_id, func.count(GameResult.id))
                .group_by(GameResult.player_id).all())
    counts = {pid: c for pid, c in q_counts}
    players = Player.query.order_by(Player.name.asc()).all()  # incluye activos e inactivos
    return render_template("players.html", players=players, counts=counts)

@app.route("/admin/players/add", methods=["POST"])
def player_add():
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("index"))
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("El nombre no puede estar vacío.", "warning")
        return redirect(url_for("players_admin"))
    exists = Player.query.filter(db.func.lower(Player.name) == name.lower()).first()
    if exists:
        flash(f"Ya existe un jugador llamado '{name}'.", "warning")
        return redirect(url_for("players_admin"))
    db.session.add(Player(name=name, active=True))
    db.session.commit()
    flash(f"Jugador '{name}' agregado (activo).", "success")
    return redirect(url_for("players_admin"))

@app.route("/admin/players/<int:pid>/toggle", methods=["POST"])
def player_toggle(pid):
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("index"))
    p = Player.query.get_or_404(pid)
    p.active = not p.active
    db.session.commit()
    flash(f"Jugador '{p.name}' ahora está {'activo' if p.active else 'inactivo'}.", "info")
    return redirect(url_for("players_admin"))


# ========== ADMIN: Rondas (crear / eliminar) ==========

@app.route("/rounds/add", methods=["POST"])
def round_add():
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    # próximo número = max(número en RoundInfo, número en Game) + 1
    max_ri = db.session.query(db.func.max(RoundInfo.number)).scalar() or 0
    max_g  = db.session.query(db.func.max(Game.round_number)).scalar() or 0
    next_no = max(max_ri, max_g) + 1

    ri = RoundInfo(number=next_no)
    db.session.add(ri)
    db.session.commit()
    flash(f"Ronda {next_no} creada (vacía). Usa 'Editar mesas' para asignar jugadores.", "success")
    return redirect(url_for("rounds_view"))


@app.route("/rounds/<int:round_no>/delete", methods=["POST"])
def round_delete(round_no):
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    # Borra todas las mesas de la ronda (con sus resultados) y el RoundInfo
    games = Game.query.filter_by(round_number=round_no).all()
    for g in games:
        db.session.delete(g)  # cascade elimina GameResult
    ri = RoundInfo.query.filter_by(number=round_no).first()
    if ri:
        db.session.delete(ri)
    db.session.commit()
    flash(f"Ronda {round_no} eliminada por completo.", "warning")
    return redirect(url_for("rounds_view"))

# --- util ---
def get_or_create_game(round_no: int, table_no: int) -> Game:
    g = Game.query.filter_by(round_number=round_no, table_no=table_no).first()
    if not g:
        g = Game(round_number=round_no, table_no=table_no)
        db.session.add(g)
        db.session.flush()
    return g

@app.route("/rounds/<int:round_no>/edit", methods=["GET", "POST"])
def round_edit(round_no):
    # Solo admin edita
    if not session.get("is_admin"):
        flash("No autorizado.", "danger")
        return redirect(url_for("rounds_view"))

    players = Player.query.filter_by(active=True).order_by(Player.name.asc()).all()
    all_ids = [p.id for p in players]

    # Carga estado actual de la ronda
    g1 = Game.query.filter_by(round_number=round_no, table_no=1).first()
    g2 = Game.query.filter_by(round_number=round_no, table_no=2).first()
    ri = RoundInfo.query.filter_by(number=round_no).first()

    t1_ids = set([r.player_id for r in (g1.results if g1 else [])])
    t2_ids = set([r.player_id for r in (g2.results if g2 else [])])
    bye_id = ri.bye_player_id if ri else None

    if request.method == "POST":
        # Recoger selección: slot_<pid> = "1" | "2" | "bye" | (vacío)
        t1_new, t2_new, bye_new = set(), set(), None
        for pid in all_ids:
            val = request.form.get(f"slot_{pid}", "")
            if val == "1":
                t1_new.add(pid)
            elif val == "2":
                t2_new.add(pid)
            elif val == "bye":
                bye_new = pid

        # Si no marcaste bye, deduzco el sobrante
        if bye_new is None:
            leftover = set(all_ids) - t1_new - t2_new
            if len(leftover) == 1:
                bye_new = leftover.pop()
            else:
                flash("Debes dejar exactamente 1 jugador fuera de las mesas (descanso).", "warning")
                return redirect(url_for("round_edit", round_no=round_no))

        # Validaciones
        if len(t1_new) != 4 or len(t2_new) != 4:
            flash("Cada mesa debe tener exactamente 4 jugadores.", "warning")
            return redirect(url_for("round_edit", round_no=round_no))
        if len({*t1_new, *t2_new, bye_new}) != 9:
            flash("Un jugador no puede estar repetido ni faltar. Revisa la selección.", "warning")
            return redirect(url_for("round_edit", round_no=round_no))
        if t1_new & t2_new:
            flash("Un jugador no puede estar en ambas mesas.", "warning")
            return redirect(url_for("round_edit", round_no=round_no))

        # Guardar composición (reset de posiciones si cambian los jugadores)
        ri = ri or RoundInfo(number=round_no)
        ri.bye_player_id = bye_new
        db.session.add(ri)

        g1 = get_or_create_game(round_no, 1)
        g2 = get_or_create_game(round_no, 2)

        # borro resultados actuales y creo los nuevos (posiciones en None)
        GameResult.query.filter_by(game_id=g1.id).delete(synchronize_session=False)
        GameResult.query.filter_by(game_id=g2.id).delete(synchronize_session=False)
        for pid in sorted(t1_new):
            db.session.add(GameResult(game_id=g1.id, player_id=pid, position=None))
        for pid in sorted(t2_new):
            db.session.add(GameResult(game_id=g2.id, player_id=pid, position=None))

        db.session.commit()
        flash(f"Ronda {round_no}: mesas y descanso actualizados.", "success")
        return redirect(url_for("rounds_view"))

    # GET
    context = {
        "round_no": round_no,
        "players": players,
        "t1_ids": t1_ids,
        "t2_ids": t2_ids,
        "bye_id": bye_id,
        "is_admin": True
    }
    return render_template("round_edit.html", **context)

# ---------- LOGIN ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Login correcto. ¡Bienvenido, admin!", "success")
            return redirect(url_for("index"))
        flash("Usuario o contraseña incorrectos", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("is_admin", None)
    flash("Sesión cerrada.", "info")
    return redirect(url_for("index"))

# ---------- INICIALIZACIÓN ----------
def init_db_and_import():
    with app.app_context():
        db.create_all()
        if Player.query.count() == 0:
            seed_players()
        import_initial_rounds()

if __name__ == "__main__":
    init_db_and_import()
    app.run(debug=True)  # http://127.0.0.1:5000

import os
import re
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user, login_required
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import and_, or_
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-only-change-this-before-deploying')
database_url = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'pingline.db')}")
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins=None, manage_session=True)

# Online presence is process-local. Deploy this starter with one web instance.
online_users = set()

def utc_iso(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(24), unique=True, nullable=False, index=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    about = db.Column(db.String(120), default='Hey there! I am using PingLine.')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    body = db.Column(db.String(2000), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    sender = db.relationship('User', foreign_keys=[sender_id])

class Block(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('blocker_id', 'blocked_id'),)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_now():
    return {'year': datetime.now().year}

@app.route('/')
def index():
    if current_user.is_authenticated:
        return render_template('chat.html')
    return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        errors = []
        if not re.fullmatch(r'[A-Za-z0-9_]{3,24}', username):
            errors.append('Username must be 3–24 characters: letters, numbers or underscore.')
        if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
            errors.append('Enter a valid email address.')
        if len(password) < 10:
            errors.append('Password must be at least 10 characters.')
        if User.query.filter(or_(User.username.ilike(username), User.email == email)).first():
            errors.append('That username or email is already registered.')
        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('auth.html', mode='register')
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash('Your PingLine account is ready.', 'success')
        return redirect(url_for('index'))
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        identity = request.form.get('identity', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter(or_(User.username.ilike(identity), User.email == identity.lower())).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Incorrect username/email or password.', 'error')
    return render_template('auth.html', mode='login')

@app.post('/logout')
@login_required
def logout():
    online_users.discard(current_user.id)
    logout_user()
    return redirect(url_for('index'))

@app.get('/api/me')
@login_required
def me():
    return jsonify({'id': current_user.id, 'username': current_user.username, 'about': current_user.about})

@app.post('/api/profile')
@login_required
def update_profile():
    about = request.json.get('about', '').strip()[:120]
    current_user.about = about
    db.session.commit()
    return jsonify({'ok': True, 'about': about})

@app.get('/api/users')
@login_required
def search_users():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    blocked_ids = db.session.query(Block.blocked_id).filter_by(blocker_id=current_user.id)
    blocking_ids = db.session.query(Block.blocker_id).filter_by(blocked_id=current_user.id)
    users = User.query.filter(User.id != current_user.id, User.username.ilike(f'%{q}%'),
                              ~User.id.in_(blocked_ids), ~User.id.in_(blocking_ids)).order_by(User.username).limit(20).all()
    return jsonify([{'id': u.id, 'username': u.username, 'about': u.about, 'online': u.id in online_users} for u in users])

@app.get('/api/chats')
@login_required
def recent_chats():
    rows = db.session.query(Message).filter(or_(Message.sender_id == current_user.id,
                                                Message.recipient_id == current_user.id)).order_by(Message.created_at.desc()).all()
    seen, result = set(), []
    for msg in rows:
        other_id = msg.recipient_id if msg.sender_id == current_user.id else msg.sender_id
        if other_id in seen:
            continue
        seen.add(other_id)
        other = db.session.get(User, other_id)
        if other and not Block.query.filter(or_(and_(Block.blocker_id == current_user.id, Block.blocked_id == other_id),
                                                  and_(Block.blocker_id == other_id, Block.blocked_id == current_user.id))).first():
            result.append({'id': other.id, 'username': other.username, 'about': other.about,
                           'online': other.id in online_users, 'last_message': msg.body,
                           'time': utc_iso(msg.created_at)})
    return jsonify(result)

@app.get('/api/messages/<int:other_id>')
@login_required
def get_messages(other_id):
    other = db.session.get(User, other_id)
    if not other or other_id == current_user.id:
        return jsonify({'error': 'User not found'}), 404
    if Block.query.filter(or_(and_(Block.blocker_id == current_user.id, Block.blocked_id == other_id),
                               and_(Block.blocker_id == other_id, Block.blocked_id == current_user.id))).first():
        return jsonify({'error': 'This conversation is unavailable.'}), 403
    messages = Message.query.filter(or_(and_(Message.sender_id == current_user.id, Message.recipient_id == other_id),
                                        and_(Message.sender_id == other_id, Message.recipient_id == current_user.id)))\
                             .order_by(Message.created_at.desc()).limit(100).all()
    messages.reverse()
    for msg in messages:
        if msg.recipient_id == current_user.id and msg.read_at is None:
            msg.read_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify([{'id': m.id, 'sender_id': m.sender_id, 'recipient_id': m.recipient_id,
                     'body': m.body, 'time': utc_iso(m.created_at), 'read': m.read_at is not None} for m in messages])

@app.post('/api/block/<int:other_id>')
@login_required
def block_user(other_id):
    if other_id == current_user.id or not db.session.get(User, other_id):
        return jsonify({'error': 'Invalid user'}), 400
    if not Block.query.filter_by(blocker_id=current_user.id, blocked_id=other_id).first():
        db.session.add(Block(blocker_id=current_user.id, blocked_id=other_id))
        db.session.commit()
    return jsonify({'ok': True})

@app.post('/api/report/<int:other_id>')
@login_required
def report_user(other_id):
    # Reports are recorded locally for this starter; configure an admin workflow before public launch.
    if other_id == current_user.id or not db.session.get(User, other_id):
        return jsonify({'error': 'Invalid user'}), 400
    app.logger.warning('USER_REPORT reporter=%s reported=%s', current_user.id, other_id)
    return jsonify({'ok': True})

@socketio.on('connect')
def socket_connect(auth=None):
    if not current_user.is_authenticated:
        return False
    join_room(f'user_{current_user.id}')
    online_users.add(current_user.id)
    emit('presence', {'user_id': current_user.id, 'online': True}, broadcast=True, include_self=False)

@socketio.on('disconnect')
def socket_disconnect(reason=None):
    if current_user.is_authenticated:
        online_users.discard(current_user.id)
        emit('presence', {'user_id': current_user.id, 'online': False}, broadcast=True)

@socketio.on('send_message')
def socket_send_message(data):
    if not current_user.is_authenticated:
        emit('message_error', {'error': 'Please sign in again.'})
        return
    try:
        recipient_id = int(data.get('recipient_id'))
    except (TypeError, ValueError, AttributeError):
        emit('message_error', {'error': 'Choose a valid recipient.'})
        return
    body = (data.get('body') or '').strip() if isinstance(data, dict) else ''
    recipient = db.session.get(User, recipient_id)
    if not recipient or recipient_id == current_user.id or not body or len(body) > 2000:
        emit('message_error', {'error': 'Message must be 1–2000 characters and have a valid recipient.'})
        return
    blocked = Block.query.filter(or_(and_(Block.blocker_id == current_user.id, Block.blocked_id == recipient_id),
                                     and_(Block.blocker_id == recipient_id, Block.blocked_id == current_user.id))).first()
    if blocked:
        emit('message_error', {'error': 'This conversation is unavailable.'})
        return
    msg = Message(sender_id=current_user.id, recipient_id=recipient_id, body=body)
    db.session.add(msg)
    db.session.commit()
    payload = {'id': msg.id, 'sender_id': current_user.id, 'recipient_id': recipient_id,
               'body': msg.body, 'time': utc_iso(msg.created_at), 'read': False}
    emit('new_message', payload, room=f'user_{current_user.id}')
    emit('new_message', payload, room=f'user_{recipient_id}')

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, allow_unsafe_werkzeug=True)

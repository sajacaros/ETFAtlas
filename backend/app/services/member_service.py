"""관리자 멤버 관리: 목록, 관리자 권한, 강제 로그아웃, 삭제."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..models.auth_session import AuthSession
from ..models.role import Role, UserRole
from ..models.user import User
from ..utils.time import utcnow
from .graph_service import GraphService


class MemberNotFoundError(Exception):
    pass


class SelfActionError(Exception):
    """관리자가 자기 자신의 권한 회수·삭제를 시도함 (관리자가 0명이 되는 것을 막는다)."""


class MemberService:
    def __init__(self, db: Session):
        self.db = db

    def list_members(self) -> list[dict]:
        """가입순 회원 목록. 최근 로그인은 남아 있는 세션 중 가장 최근 생성 시각이라, 세션이 모두 만료되면 비어 있다."""
        rows = self.db.execute(text("""
            SELECT u.id, u.username, u.name, u.created_at,
                   EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                           WHERE ur.user_id = u.id AND r.name = 'admin') AS is_admin,
                   inviter.username AS invited_by,
                   (SELECT count(*) FROM auth_sessions s
                    WHERE s.user_id = u.id AND s.expires_at > :now) AS active_sessions,
                   (SELECT max(s.created_at) FROM auth_sessions s WHERE s.user_id = u.id) AS last_login_at,
                   (SELECT count(*) FROM portfolios p WHERE p.user_id = u.id) AS portfolio_count
            FROM users u
            LEFT JOIN invitations i ON i.used_by = u.id
            LEFT JOIN users inviter ON inviter.id = i.created_by
            ORDER BY u.created_at, u.id
        """), {"now": utcnow()}).mappings().all()
        return [
            {
                **row,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "last_login_at": row["last_login_at"].isoformat() if row["last_login_at"] else None,
            }
            for row in rows
        ]

    def _get(self, user_id: int) -> User:
        user = self.db.get(User, user_id)
        if user is None:
            raise MemberNotFoundError()
        return user

    def set_admin(self, user_id: int, is_admin: bool, acting_admin_id: int) -> None:
        """admin 역할을 주거나 뺀다. member 역할은 그대로 두지 않고 admin과 서로 바꾼다."""
        if user_id == acting_admin_id:
            raise SelfActionError()
        self._get(user_id)
        roles = {r.name: r.id for r in self.db.query(Role).filter(Role.name.in_(["admin", "member"]))}
        add, remove = ("admin", "member") if is_admin else ("member", "admin")
        self.db.query(UserRole).filter(
            UserRole.user_id == user_id, UserRole.role_id == roles[remove]
        ).delete(synchronize_session=False)
        exists = self.db.query(UserRole.id).filter(
            UserRole.user_id == user_id, UserRole.role_id == roles[add]
        ).first()
        if not exists:
            self.db.add(UserRole(user_id=user_id, role_id=roles[add]))
        self.db.commit()

    def revoke_sessions(self, user_id: int) -> int:
        """회원의 모든 로그인 세션을 끊는다. 끊은 세션 수 반환."""
        self._get(user_id)
        count = self.db.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
        self.db.commit()
        return count

    def delete_member(self, user_id: int, acting_admin_id: int) -> None:
        """회원 삭제. 포트폴리오·세션·역할·재설정 링크는 CASCADE로 함께 지워지고,
        챗봇 로그·코드 예제·초대 기록은 작성자만 비운다. 그래프의 즐겨찾기(User 노드)도 지운다."""
        if user_id == acting_admin_id:
            raise SelfActionError()
        user = self._get(user_id)
        GraphService(self.db).execute_cypher(
            "MATCH (u:User {user_id: $user_id}) DETACH DELETE u RETURN 1",
            {"user_id": user_id}, raise_errors=True,
        )
        self.db.delete(user)
        self.db.commit()

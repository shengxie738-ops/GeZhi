from fastapi import APIRouter

from app.api.endpoints import academic, agents, analytics, auth, chat, code_repository, dashboard, evaluator, exams, forum, gitea_accounts, homework, journal, language, profile, ranked, team_git, user_center, user_models, user_knowledge, visual_guide, learning_diagnosis, teacher_learning_diagnosis, teacher_lesson_prep

api_router = APIRouter()

api_router.include_router(auth.router, prefix="", tags=["auth"])
api_router.include_router(academic.router, prefix="", tags=["academic"])
api_router.include_router(agents.router, prefix="", tags=["agents"])
api_router.include_router(chat.router, prefix="", tags=["chat"])
api_router.include_router(profile.router, prefix="", tags=["profile"])
api_router.include_router(ranked.router, prefix="", tags=["ranked"])
api_router.include_router(user_center.router, prefix="", tags=["user_center"])
api_router.include_router(user_knowledge.router, prefix="", tags=["user_knowledge"])
api_router.include_router(user_models.router, prefix="", tags=["user_models"])
api_router.include_router(homework.router, prefix="", tags=["homework"])
api_router.include_router(exams.router, prefix="", tags=["exams"])
api_router.include_router(evaluator.router, prefix="", tags=["evaluator"])
api_router.include_router(forum.router, prefix="", tags=["forum"])
api_router.include_router(code_repository.router, prefix="", tags=["code_repository"])
api_router.include_router(gitea_accounts.router, prefix="", tags=["gitea_accounts"])
api_router.include_router(team_git.router, prefix="", tags=["team_git"])
api_router.include_router(analytics.router, prefix="", tags=["analytics"])
api_router.include_router(visual_guide.router, prefix="", tags=["visual_guide"])
api_router.include_router(dashboard.router, prefix="", tags=["dashboard"])
api_router.include_router(journal.router, prefix="", tags=["journal"])
api_router.include_router(learning_diagnosis.router, prefix="", tags=["learning_diagnosis"])
api_router.include_router(teacher_learning_diagnosis.router, prefix="", tags=["teacher_learning_diagnosis"])
api_router.include_router(teacher_lesson_prep.router, prefix="", tags=["teacher_lesson_prep"])
api_router.include_router(language.router, prefix="", tags=["language"])

from app.api.endpoints import git_coach
api_router.include_router(git_coach.router, prefix="", tags=["git_coach"])

from app.api.endpoints import teaching
api_router.include_router(teaching.router, prefix="", tags=["teaching"])

from app.api.endpoints import teaching_assessment
api_router.include_router(teaching_assessment.router, prefix="", tags=["teaching-assessment"])

from app.api.endpoints import teacher_work
api_router.include_router(teacher_work.router, prefix="", tags=["teacher-work"])

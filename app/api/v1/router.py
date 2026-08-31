from fastapi import APIRouter

from app.controllers.attendance_controller import router as attendance_router
from app.controllers.auth_controller import router as auth_router
from app.controllers.commission_controller import router as commission_router
from app.controllers.credit_customer_controller import router as credit_customer_router
from app.controllers.employee_controller import router as employee_router
from app.controllers.expense_controller import router as expense_router
from app.controllers.fuel_entry_controller import router as fuel_entry_router
from app.controllers.lubricant_controller import router as lubricant_router
from app.controllers.offer_controller import router as offer_router
from app.controllers.station_controller import router as station_router
from app.controllers.upload_controller import router as upload_router
from app.controllers.user_controller import router as user_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(user_router)
api_router.include_router(station_router)
api_router.include_router(employee_router)
api_router.include_router(attendance_router)
api_router.include_router(lubricant_router)
api_router.include_router(expense_router)
api_router.include_router(commission_router)
api_router.include_router(credit_customer_router)
api_router.include_router(offer_router)
api_router.include_router(fuel_entry_router)
api_router.include_router(upload_router)

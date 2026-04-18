from fastapi import APIRouter

router = APIRouter(prefix="/api/trajectory", tags=["Artemis Trajectory"])


@router.get("/artemis-data")
async def artemis_data():
    """Return Artemis-I DRO trajectory data points for frontend ECharts animation."""
    from web.backend.services.artemis_trajectory import get_trajectory_data
    return get_trajectory_data()
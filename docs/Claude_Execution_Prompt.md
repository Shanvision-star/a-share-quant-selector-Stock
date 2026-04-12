# Claude-Ready Execution Prompt

## Objective
Enhance the A-share Quantitative Stock Selector system by improving data persistence, unifying job orchestration, and creating a formal results workbench.

## Implementation Plan

### 1. Data Persistence
- Replace JSON-based caching with SQLite for scalability and reliability.
- Migrate existing data stored in JSON files to SQLite tables.
- Update data access logic to use SQLite queries.

### 2. Unified Job Orchestration
- Centralize job scheduling and execution using Celery.
- Implement a unified API endpoint for triggering jobs.
- Integrate job status tracking and real-time updates via SSE.

### 3. Results Workbench
- Develop a dedicated web interface for viewing and managing results.
- Add filtering, sorting, and exporting options for stock selection results.
- Optimize the frontend for performance with large datasets.

### 4. API Enhancements
- Expand existing APIs to support new features (e.g., history tracking, detailed queries).
- Ensure backward compatibility with current API consumers.

### 5. Frontend Improvements
- Simplify the homepage to display a summary of stock selection results.
- Upgrade the job management page with real-time updates and detailed logs.
- Enhance the stock details page with additional metrics and visualizations.

### 6. Testing and Deployment
- Write unit tests for new backend and frontend components.
- Perform integration testing to ensure seamless interaction between modules.
- Containerize the application using Docker for consistent deployment.

## Execution Steps

1. **Preparation**
   - Set up development environments for backend and frontend.
   - Install necessary dependencies (e.g., SQLite, Celery).

2. **Backend Development**
   - Implement SQLite integration and migrate data.
   - Develop new API endpoints for job orchestration and results management.
   - Integrate Celery for job scheduling and execution.

3. **Frontend Development**
   - Design and implement the results workbench.
   - Update existing pages with new features and optimizations.
   - Test frontend components with mock data.

4. **Testing**
   - Write and execute unit tests for backend and frontend.
   - Perform end-to-end testing with real data.

5. **Deployment**
   - Build Docker images for the backend and frontend.
   - Deploy the application to the production server.
   - Monitor the system for issues and optimize as needed.

## Key Considerations
- Ensure data consistency during the migration from JSON to SQLite.
- Optimize API response times for large datasets.
- Maintain a user-friendly interface while adding new features.

## Timeline
| Phase            | Duration (days) |
|------------------|-----------------|
| Preparation      | 2               |
| Backend Development | 5           |
| Frontend Development | 7           |
| Testing & Optimization | 3         |
| Deployment       | 3               |
| **Total**        | **20 days**     |

## Notes
This document serves as a standalone execution prompt for implementing the proposed enhancements to the A-share Quantitative Stock Selector system. Adjustments can be made based on specific requirements or constraints.
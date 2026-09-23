## Project
Mawta is a gradebook and classroom-evidence app for schoolteachers: attendance,
grading, competency/criteria tracking, and notifications across eight screens
(Home, Class dashboard, Lesson/attendance, Criterios, Evidence grid, Student
grades, Notifications, Profile).

Stack: Go 1.26 (`chi` + `pgx/v5`, hand-written SQL, no ORM) for the API in
`mawta-server/`, SvelteKit 2 + Svelte 5 + TypeScript for the UI in
`mawta-ui/`, Postgres (pgvector image) as the database, Docker/Caddy for
deploy (`deploy/`).



'''

An eval is an automated test for AI behavior. Normal tests check code (“does this route return 404?”), but the AI's output changes 
every time, so you can't test for one exact answer. An eval runs the AI many times and scores what it did.

What you'd evaluate in your voice product
Part	Example question
Interviewer behavior	Does Iris ask a question about something in the résumé? Does she stay on topic and avoid giving feedback?
Scoring	Does the same transcript get the same score every time?
Hallucination	Does the report quote something the candidate never said?
Speed	How long until Iris starts speaking?
How to write one, in 4 steps
Make test cases. Each one is an input: a résumé plus a job description, and a fake candidate (another LLM playing a strong, weak or rambling candidate).
Run the system. Start with text mode, with no audio, since it's fast and cheap. Layer 9 does this.
Define what “good” means as checks:
Rule checks (code): “the transcript has at least 5 questions”, “no response is longer than 3 sentences”.
LLM-as-judge: a second LLM gets the transcript and a question like “Did Iris ask about a project from the résumé? Answer yes or no with a quote.”
Run 100+ cases and report the pass rate. If you change the prompt and the pass rate drops from 90% to 70%, you've caught a regression before users do.
A tiny example
Case:   résumé says "built a Redis cache at WESEE"
Run:    fake candidate interviews with Iris for 5 turns
Check:  did any of Iris's questions mention caching or Redis?  (judge: yes/no)

Over 100 résumés, “yes” in 87 cases means 87% résumé-awareness. That number is your eval result.

'''
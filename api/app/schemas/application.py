

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.application import ApplicationStatus


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    candidate_id: uuid.UUID
    status: ApplicationStatus
    created_at: datetime
    updated_at: datetime


'''
What it does ?
=>ApplicationResponse: what the API returns for an application. It reads straight from the Application object (from_attributes=True).
=>No resume_path: the server's file path is internal, so it's never sent to the browser. If someone needs to see the résumé, we'll add a download route that checks permissions first.
'''


'''
Why there is no “create” schema ??

Applying isn't a JSON body. It's a file upload (multipart/form-data): the job id comes from the URL 
(POST /jobs/{job_id}/apply) and the PDF comes as an uploaded file. The candidate id comes from the token, 
as with employer_id earlier. FastAPI reads the file directly with UploadFile, so the router will handle 
it, with no Pydantic schema needed. That's what python-multipart (installed in Step 2) is for.

'''
SpecForge is an AI engineering planning assistant.

Its purpose is to transform messy engineering meeting transcripts into
structured, actionable and traceable engineering plans.

The initial version must run completely locally.

AI inference:
- Ollama
- Qwen 3 8B

Backend:
- Python
- FastAPI
- Pydantic

Frontend:
- React
- TypeScript
- Vite

Initial V1 scope:
1. User pastes an engineering meeting transcript.
2. Backend sends it to the local LLM.
3. LLM extracts:
   - decisions
   - requirements
   - tasks
   - risks
   - open questions
4. LLM generates acceptance criteria for tasks.
5. Backend validates the result using Pydantic.
6. Frontend displays the engineering plan.

Do not add:
- cloud APIs
- paid services
- databases
- authentication
- GitHub integration
- Whisper
- vector databases
- LangChain
- LangGraph

These will only be considered after V1 works.

## Traceability

Relationships are optional ID references on the existing Pydantic
domain objects. Empty lists are valid. The application never invents
links to make the graph look complete.

    Decision
      ↓
    Requirement
      ↓
    Task
      ↓
    Implementation Plan Step

Risks and open questions may also point at requirements when the
meeting makes that connection explicit. A requirement may point at
related decisions and risks the same way.

These IDs explain how items relate. They do not replace evidence.
`source_reference`, `source_references`, and plan-step `evidence`
remain the provenance layer: a kept claim still needs a
transcript-backed excerpt.

Item IDs are assigned by the application, not trusted from the LLM.
A `MeetingAnalysis` is rejected if a relationship points at an ID
that is not in the same record. Implementation-plan steps may suggest
requirement and task IDs; unknown IDs are stripped, and a step with
no remaining record-backed evidence is dropped.
"""
Esquemas Pydantic para validación y guided decoding
"""
from pydantic import BaseModel, Field
from typing import List

class QuestionTypes(BaseModel):
    """Esquema para tipos de preguntas"""
    Question_Types: List[str] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Lista de tipos de pregunta generados"
    )

class Selection(BaseModel):
    """Esquema para selección de personaje y tipo de pregunta"""
    Character: str = Field(..., min_length=1, max_length=1000, description="Personaje seleccionado")
    Question_Type: str = Field(..., min_length=1, max_length=200, description="Tipo de pregunta seleccionado")
    Difficulty: str = Field(..., min_length=1, max_length=50, description="Nivel de dificultad")

class QueryOnly(BaseModel):
    """Esquema para generación solo de pregunta"""
    query: str = Field(..., min_length=5, max_length=1000, description="Query generada")

class QueryWithAnswer(BaseModel):
    """Esquema para generación de pregunta Y respuesta juntas"""
    query: str = Field(..., min_length=5, max_length=1000, description="Query generada")
    answer: str = Field(..., min_length=5, max_length=3000, description="Respuesta a la query")

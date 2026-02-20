import json
import re
from pathlib import Path


def load_year_payload(path, year=None):
    raw = Path(path).read_text()
    doc = json.loads(raw)
    schema_version = doc.get('schemaVersion') if isinstance(doc, dict) else None

    if isinstance(doc, dict) and 'years' in doc:
        years_obj = doc.get('years') or {}
        if year is None:
            if len(years_obj) != 1:
                raise ValueError('File contains multiple years; pass --year explicitly.')
            year_key = next(iter(years_obj.keys()))
            payload = years_obj[year_key]
            year = int(year_key)
        else:
            payload = years_obj.get(str(year))
            if payload is None:
                raise ValueError(f'Year {year} not found in file.')
    else:
        payload = doc
        if year is None:
            year = int(payload.get('year'))

    if not isinstance(payload, dict):
        raise ValueError('Invalid year payload.')
    return int(year), payload, schema_version


def validate_year_payload(year, payload):
    errors = []
    warnings = []

    required_keys = ['label', 'categories', 'films', 'nominations']
    for key in required_keys:
        if key not in payload:
            errors.append(f'Missing required key: {key}')

    categories = payload.get('categories') or []
    films = payload.get('films') or []
    nominations = payload.get('nominations') or []
    default_seen = payload.get('defaultSeenFilmIds') or []

    category_names = [c.get('name', '').strip() for c in categories]
    if any(not name for name in category_names):
        errors.append('All categories must have a non-empty name.')
    if len(set(category_names)) != len(category_names):
        errors.append('Category names must be unique within the year.')

    source_ids = []
    external_ids = []
    for film in films:
        source_id = str(film.get('id', '')).strip()
        title = str(film.get('title', '')).strip()
        external_id = str(film.get('externalId', '')).strip()
        if not source_id:
            errors.append('Each film must have a non-empty id.')
        if not title:
            errors.append(f'Film {source_id or "<missing id>"} has empty title.')
        source_ids.append(source_id)
        if external_id:
            external_ids.append(external_id)
            if not re.match(r'^tt\d+$', external_id):
                warnings.append(
                    f'Film {source_id} has externalId "{external_id}" not matching tt1234567 format.'
                )

    if len(set(source_ids)) != len(source_ids):
        errors.append('Film ids must be unique within the year payload.')
    if len(set(external_ids)) != len(external_ids):
        errors.append('externalId values must be unique within the year payload.')

    source_id_set = set(source_ids)
    category_set = set(category_names)
    for n in nominations:
        category_name = str(n.get('category', '')).strip()
        film_id = str(n.get('filmId', '')).strip()
        if category_name not in category_set:
            errors.append(f'Nomination references unknown category: {category_name}')
        if film_id not in source_id_set:
            errors.append(f'Nomination references unknown filmId: {film_id}')

    for film_id in default_seen:
        if film_id not in source_id_set:
            errors.append(f'defaultSeenFilmIds contains unknown filmId: {film_id}')

    return {
        'year': int(year),
        'errors': errors,
        'warnings': warnings,
        'counts': {
            'categories': len(categories),
            'films': len(films),
            'nominations': len(nominations),
            'defaultSeenFilmIds': len(default_seen),
        },
    }

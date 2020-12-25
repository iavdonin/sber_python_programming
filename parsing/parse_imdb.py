import argparse

import requests
from bs4 import BeautifulSoup
from typing import Set, Dict, Union

IMDB_ADDRESS = 'https://www.imdb.com/'
SEARCH_ADDRESS = IMDB_ADDRESS + 'search/title'
FILM_INFO_ROOT_ADDRESS = IMDB_ADDRESS + 'title/'

SCRIPT_DESCRIPTION = """Скрипт для парсинга IMDB. Собирает следующие атрибуты фильмов, подходящих под заданные """ + \
                     """параметры: название, жанр, рейтинг, топ каста (stars), тип (сериал, фильм и т.д.), блоки Details, """ + \
                     """Box office, Technical specs."""
INFO_FIELDS = ('index', 'name', 'genre', 'rating', 'details', 'box_office', 'tech_specs')
SEPARATOR = '\t'

# init available arguments
response = requests.get(SEARCH_ADDRESS)
soup = BeautifulSoup(response.content, features='html.parser')
COUNTRY_TO_ABBR_MAPPING: Dict[str, str] = {
    tag.text: tag['value'] for tag in soup.find('select', attrs={'class': 'countries'}).children if tag != '\n'
}
TITLE_TYPES: Set[str] = {tag['value'] for tag in soup.find_all('input', attrs={'name': 'title_type'})}
GENRES: Set[str] = {tag['value'] for tag in soup.find_all('input', attrs={'name': 'genres'})}
NUM_FILMS_ON_ONE_PAGE = 50


def is_date_correct(date: str) -> bool:
    return len(date) == 10 and date[:4].isdigit() and date[5:7].isdigit() and date[8:10].isdigit()


def get_html_params(args: argparse.Namespace) -> Dict[str, Union[str, int]]:
    params: Dict[str, Union[str, int]] = {}

    if args.title_type:
        for title_type in args.title_type.split():
            if title_type.lower() not in TITLE_TYPES:
                raise Exception(f"{title_type} isn't one of available types")
        params['title_type'] = args.title_type.split()

    if args.release_date_from:
        if is_date_correct(args.release_date_from):
            params['release_date'] = args.release_date_from
        else:
            raise Exception('Date must be in YYYY-MM-DD format')
    else:
        params['release_date'] = ''
    params['release_date'] += ','
    if args.release_date_to:
        if is_date_correct(args.release_date_to):
            params['release_date'] += args.release_date_to
        else:
            raise Exception('Date must be in YYYY-MM-DD format')
    else:
        params['release_date'] += ''

    if args.genres:
        for genre in args.genres:
            if genre.lower() not in GENRES:
                raise Exception(f"{genre} isn't one of available genres")
        params['genres'] = args.genres.split()

    if float(args.min_user_rating >= 0.) and float(args.min_user_rating) <= 10.:
        params['user_rating'] = f'{args.min_user_rating}'
    else:
        raise Exception('Min user rating must be a number from 0 to 10')
    params['user_rating'] += ','
    if float(args.max_user_rating >= 0.) and float(args.max_user_rating) <= 10.:
        params['user_rating'] += f'{args.max_user_rating}'
    else:
        raise Exception('Min user rating must be a number from 0 to 10')

    if args.countries:
        for country in args.countries:
            if country not in COUNTRY_TO_ABBR_MAPPING.keys():
                raise Exception(f'Unknown country {country}')
        params['country'] = args.countries.split()
    params['start'] = 1
    return params


def handle_block(block: BeautifulSoup) -> str:
    strings = []
    for tag in block.find_all('div', attrs={'class': 'txt-block'}):
        strings.append(' '.join(tag.text.split()).replace('See more »', ''))
    return '\\n'.join(strings)


def parse_imdb(params: Dict['str', Union[str, int]]) -> Dict['str', Union[str, int]]:
    while params['start'] < 1000:
        query_html = requests.get(SEARCH_ADDRESS, params=params)
        query_soup = BeautifulSoup(query_html.text, features='html.parser')
        for film_container in query_soup.find_all('div', attrs={'class': 'lister-item-content'}):
            index = film_container.find('span', attrs={'class': 'lister-item-index unbold text-primary'}).text.strip()
            name = film_container.find('h3', attrs={'class': 'lister-item-header'}).find('a').text.strip()
            genre = film_container.find('span', attrs={'class': 'genre'}).text.strip()
            rating = film_container.find('div', attrs={'class': 'ratings-bar'}).find('div', attrs={'name': 'ir'})[
                'data-value'].strip()
            film_link = film_container.find('a')['href']
            film_id = film_link.split('/')[-2]
            film_url = FILM_INFO_ROOT_ADDRESS + film_id
            film_html = requests.get(film_url)
            film_soup = BeautifulSoup(film_html.text, features='html.parser')
            details_container = str(film_soup.find('div', id='titleDetails'))
            details_parts = details_container.split('<hr/>')
            details, box_office, tech_specs = (None for _ in range(3))
            for part in details_parts:
                block = BeautifulSoup(part, 'html.parser')
                block_name = block.find(['h2', 'h3']).text
                if block_name == 'Details':
                    details = handle_block(block)
                elif block_name == 'Box Office':
                    box_office = handle_block(block)
                elif block_name == 'Technical Specs':
                    tech_specs = handle_block(block)
            yield {
                'index': index,
                'name': name,
                'genre': genre,
                'rating': rating,
                'details': details or 'Null',
                'box_office': box_office or 'Null',
                'tech_specs': tech_specs or 'Null'
            }
        if query_soup.find('a', attrs={'class': 'lister-page-next next-page'}):
            params['start'] += NUM_FILMS_ON_ONE_PAGE


def main(args: argparse.Namespace):
    html_params = get_html_params(args)
    with open(args.csv_file_path, 'w', encoding='utf-8') as out_csv_file:
        out_csv_file.write(SEPARATOR.join(INFO_FIELDS) + '\n')
        for film_info in parse_imdb(html_params):
            print(f"{film_info['index']} {film_info['name']}")
            out_csv_file.write(SEPARATOR.join(film_info.values()) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=SCRIPT_DESCRIPTION)
    parser.add_argument('--csv_file_path', type=str, default='parsed_imdb.csv', help='Path to output CSV file')
    parser.add_argument('--log_file_path', type=str, default='log.txt', help='Path to log file')
    parser.add_argument('--title_type', type=str, default=None, help='Space-separated title types')
    parser.add_argument('--release_date_from', type=str, default=None,
                        help='Release date from in format YYYY-MM-DD')
    parser.add_argument('--release_date_to', type=str, default=None, help='Release date to in format YYYY-MM-DD')
    parser.add_argument('--genres', type=str, default=None, help='Genres')
    parser.add_argument('--min_user_rating', type=float, default=0, help='Minimal user rating from 0 to 10')
    parser.add_argument('--max_user_rating', type=float, default=10, help='Maximum user rating from 0 to 10')
    parser.add_argument('--countries', type=str, default=None, help='Space-separated country names')
    args = parser.parse_args()
    main(args)

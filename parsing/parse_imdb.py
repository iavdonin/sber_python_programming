import argparse
import logging
from typing import Set, Dict, Union

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from tqdm import tqdm

IMDB_ADDRESS = 'https://www.imdb.com/'
SEARCH_ADDRESS = IMDB_ADDRESS + 'search/title'
MAX_FILMS = 1000
FILM_INFO_ROOT_ADDRESS = IMDB_ADDRESS + 'title/'

SCRIPT_DESCRIPTION = """Скрипт для парсинга IMDB. Собирает следующие атрибуты фильмов, подходящих под заданные """ + \
                     """параметры: название, жанр, рейтинг, топ каста (stars), тип (сериал, фильм и т.д.), блоки Details, """ + \
                     """Box office, Technical specs."""
INFO_FIELDS = ('index', 'name', 'genre', 'rating', 'type', 'stars', 'details', 'box_office', 'tech_specs')
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

logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
handler = logging.FileHandler('parse_imdb.log', 'w', 'utf-8')
root_logger.addHandler(handler)


def is_date_correct(date: str) -> bool:
    return len(date) == 10 and date[:4].isdigit() and date[5:7].isdigit() and date[8:10].isdigit()


def get_html_params(args: argparse.Namespace) -> Dict[str, Union[str, int]]:
    params: Dict[str, Union[str, int]] = {}

    if args.title_type:
        for title_type in args.title_type.split():
            if title_type.lower() not in TITLE_TYPES:
                msg = f"{title_type} isn't one of available types"
                logging.critical(msg)
                raise Exception(msg)
        params['title_type'] = args.title_type.split()

    if args.release_date_from:
        if is_date_correct(args.release_date_from):
            params['release_date'] = args.release_date_from
        else:
            msg = 'Date must be in YYYY-MM-DD format'
            logging.critical(msg)
            raise Exception(msg)
    else:
        params['release_date'] = ''
    params['release_date'] += ','
    if args.release_date_to:
        if is_date_correct(args.release_date_to):
            params['release_date'] += args.release_date_to
        else:
            msg = 'Date must be in YYYY-MM-DD format'
            logging.critical(msg)
            raise Exception(msg)
    else:
        params['release_date'] += ''

    if args.genres:
        genres = args.genres.split()
        for genre in genres:
            if genre.lower() not in GENRES:
                msg = f"{genre} isn't one of available genres"
                logging.critical(msg)
                raise Exception(msg)
        params['genres'] = args.genres.split()

    if float(args.min_user_rating >= 0.) and float(args.min_user_rating) <= 10.:
        if float(args.min_user_rating) % 1:
            params['user_rating'] = f'{round(args.min_user_rating, 1)}'
        else:
            params['user_rating'] = f'{round(args.min_user_rating)}'
    else:
        msg = 'Min user rating must be a number from 0 to 10'
        logging.critical(msg)
        raise Exception(msg)
    params['user_rating'] += ','
    if float(args.max_user_rating >= 0.) and float(args.max_user_rating) <= 10.:
        # check is it an integer
        if float(args.max_user_rating) % 1:
            params['user_rating'] += f'{round(args.max_user_rating, 1)}'
        else:
            params['user_rating'] += f'{round(args.max_user_rating)}'
    else:
        msg = 'Min user rating must be a number from 0 to 10'
        logging.critical(msg)
        raise Exception(msg)

    if args.countries:
        for country in args.countries.split(' '):
            if country not in COUNTRY_TO_ABBR_MAPPING.keys() and country not in COUNTRY_TO_ABBR_MAPPING.values():
                msg = f'Unknown country {country}'
                logging.critical(msg)
                raise Exception(msg)
        countries = args.countries.split()
        params['countries'] = ''
        for country in countries:
            country = country if country in COUNTRY_TO_ABBR_MAPPING.values() else COUNTRY_TO_ABBR_MAPPING[country]
            country = country.lower()
            params['countries'] += country + ','
        params['countries'] = params['countries'][:-1]
    logging.info(f'Got following parameters: {params}')
    params['start'] = 1
    return params


def handle_block(block: BeautifulSoup) -> str:
    strings = []
    for tag in block.find_all('div', attrs={'class': 'txt-block'}):
        strings.append(' '.join(tag.text.split()).replace('See more »', ''))
    return '\\n'.join(strings)


def parse_imdb(params: Dict['str', Union[str, int]], n_films: int) -> Dict['str', Union[str, int]]:
    films_parsed = 0
    while films_parsed < n_films:
        query_html = requests.get(SEARCH_ADDRESS, params=params)
        query_soup = BeautifulSoup(query_html.text, features='html.parser')
        for film_container in query_soup.find_all('div', attrs={'class': 'lister-item-content'}):
            index = film_container.find('span', attrs={'class': 'lister-item-index unbold text-primary'}).text.strip()
            name = film_container.find('h3', attrs={'class': 'lister-item-header'}).find('a').text.strip()

            genre_elem = film_container.find('span', attrs={'class': 'genre'})
            genre = genre_elem.text.strip() if genre_elem else 'Null'

            rating_elem = film_container.find('div', attrs={'class': 'ratings-bar'})
            rating_elem = rating_elem.find('div', attrs={'name': 'ir'}) if rating_elem else None
            rating = rating_elem['data-value'].strip() if rating_elem else 'Null'

            film_link = film_container.find('a')['href']
            film_id = film_link.split('/')[-2]
            film_url = FILM_INFO_ROOT_ADDRESS + film_id
            film_html = requests.get(film_url)
            film_soup = BeautifulSoup(film_html.text, features='html.parser')

            # Типом будем считать то, что идет после года выпуска.
            # Если ничего не указано, присваиваем тип Movie
            type_ = film_container.find('span', class_='lister-item-year')
            if type_:
                type_ = str(type_.text)[1:-1]
                type_ = type_.replace('–', '')
                type_ = ''.join([char for char in type_ if char not in '1234567890']).strip()
                if not type_:
                    type_ = 'Movie'

            credit = film_soup.find('div', class_='credit_summary_item')
            if credit:
                stars = ''
                for tag in credit.children:
                    if tag.name == 'h4':
                        continue
                    elif tag.name == 'span':
                        break
                    elif type(tag) is NavigableString:
                        stars += str(tag)
                    else:
                        stars += tag.text
                stars = stars.strip()
            else:
                stars = 'Null'

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
                'link': film_url,
                'genre': genre,
                'rating': rating,
                'type': type_ or 'Null',
                'stars': stars,
                'details': details or 'Null',
                'box_office': box_office or 'Null',
                'tech_specs': tech_specs or 'Null'
            }
            films_parsed += 1
            if films_parsed >= n_films:
                return
            params['start'] = films_parsed + 1


def main(args: argparse.Namespace):
    html_params = get_html_params(args)
    query_html = requests.get(SEARCH_ADDRESS, params=html_params)
    query_soup = BeautifulSoup(query_html.text, features='html.parser')

    desc_span = query_soup.find('div', class_='desc').find('span')
    if desc_span:
        desc_words = desc_span.text.replace(',', '').split()
        if len(desc_words) == 2:
            n_films = int(desc_words[0])
        elif len(desc_words) == 4:
            n_films = int(desc_words[2])
        else:
            raise Exception(f'Cannot recognize string with films amount: {desc_span.text}')
    else:
        n_films = 0
    if n_films == 0:
        logging.info('No films found with passed parameters')
        return

    n_films = n_films if n_films <= MAX_FILMS else MAX_FILMS
    with open(args.csv_file_path, 'w', encoding='utf-8') as out_csv_file:
        out_csv_file.write(SEPARATOR.join(INFO_FIELDS) + '\n')
        for film_info in tqdm(parse_imdb(html_params, n_films), total=n_films):
            try:
                logging.info(f"Parsing {film_info['index']} {film_info['name']} {film_info['link']}")
            except UnicodeEncodeError:
                logging.info(f"Parsing ***Unrecognized*** {film_info['name']} {film_info['link']}")
            out_csv_file.write(SEPARATOR.join(film_info.values()) + '\n')

    logging.info(f'Parsed {n_films} films.')


if __name__ == '__main__':
    logging.info('Application has been started')
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

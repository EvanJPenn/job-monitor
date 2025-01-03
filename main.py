import json
import os
import smtplib
from email.mime.text import MIMEText
from typing import Dict, List, Union

import requests
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()


def load_yaml(filepath: str) -> Dict:
    """
    Helper for reading YAMls
    :param filepath: YAML path
    :return: Dictionary of YAML contents
    """
    with open(filepath) as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise exc


def call_job_listing_api(
    url: str, headers: Dict[str, str]
) -> Union[Dict[str, any], List[any]]:
    """
    Helper to access an API.
    :param url: API endpoint url
    :param headers: Headers for the API call
    :return: JSON response
    """
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data
    else:
        print(f"Failed to fetch data. HTTP Status Code: {response.status_code}")


def process_api_response(
    data: Union[Dict, List], firm_name: str, params: Dict[str, str]
) -> Dict[str, str]:
    """
    Process the API response to get a list of job dictionaries with consistent naming
    :param data: JSON response data
    :param firm_name: Name of target firm
    :param params: Config dictionary for processing the response
    :return: Dictionary with keys firm, title, location, link
    """
    jobs = []
    if isinstance(data, dict):
        data = data[params["key"]]

    for job in data:
        jobs.append(
            {
                "firm": firm_name,
                "title": job[params["title"]],
                "location": job[params["location"]],
                "link": job[params["link"]] if params["link"] else "",
            }
        )

    return jobs


def scrape_job_listings(firm_name: str, params: Dict[str, str]) -> Dict[str, str]:
    """
    Scrape job listings from a firm's careers page.
    :param firm_name: Name of firm
    :param params: Config dictionary for processing the response
    :return: Dictionary with keys firm, title, location, link
    """
    response = requests.get(params["url"])
    soup = BeautifulSoup(response.content, "html.parser")
    jobs = []
    for job in soup.find_all(params["job_selector_tag"], params["job_selector_attr"]):
        title = job.find(
            params["title_selector_tag"], class_=params["title_selector_class"]
        ).get_text(strip=True)
        location = job.find(
            params["location_selector_tag"],
            class_=params["location_selector_class"],
        ).get_text(strip=True)
        if tag := job.find("a", href=True):
            link = tag["href"]
        else:
            link = job["href"]
        jobs.append(
            {"firm": firm_name, "title": title, "location": location, "link": link}
        )
    return jobs


def filter_jobs(
    jobs: List[Dict[str, str]], keywords: List[str], locations: List[str]
) -> List[Dict[str, str]]:
    """
    Filter jobs based on keywords and location.
    :param jobs: List of job dictionaries
    :param keywords: List of job title keywords to filter on
    :param locations: List of locations to filter by
    :return: List of job dictionaries meeting criteria
    """
    filtered_jobs = [
        job
        for job in jobs
        if any(keyword.lower() in job["title"].lower() for keyword in keywords)
        and any(location.lower() in job["location"].lower() for location in locations)
    ]
    return filtered_jobs


def load_jobs(filepath: str) -> List:
    """
    Load previously seen jobs from a JSON file.
    :param filepath: Path to JSON file
    :return: List of job dictionaries (or an empty list)
    """
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def save_jobs(jobs: List[Dict[str, str]], filepath: str) -> None:
    """
    Saves identified jobs to a JSON file.
    :param jobs: List of job dictionaries
    :param filepath: Path to JSON file
    """
    with open(filepath, "w") as f:
        json.dump(jobs, f)


def identify_new_jobs(
    jobs: List[Dict[str, str]], seen_jobs: List[Dict[str, str]]
) -> List[Dict[str, str]]:
    """
    Return jobs that are not in the seen list.
    :param jobs: List of currently identified job dictionaries
    :param seen_jobs: List of previously identified job dictionaries
    :return: List of previously unseen job dictionaries
    """
    new_jobs = [job for job in jobs if job not in seen_jobs]
    return new_jobs


def send_email_notification(jobs: List[Dict[str, str]]) -> None:
    """
    Send job notification email via SMTP.
    :param jobs: List of job dictionaries
    """
    if not jobs:
        return

    sender = os.environ["MAIL_SENDER"]
    recipient = os.environ["MAIL_RECIPIENT"]
    body = "\n".join(
        [
            f"{job['firm']} - {job['title']} - {job['location']}\n{job['link']}"
            for job in jobs
        ]
    )

    msg = MIMEText(body)
    msg["Subject"] = "New MLE Job Openings"
    msg["From"] = sender
    msg["To"] = recipient

    host = os.environ["MAIL_HOST"]
    port = os.environ["MAIL_PORT"]

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(sender, os.environ["MAIL_PASSWORD"])
        server.send_message(msg)


if __name__ == "__main__":
    # Load configs
    config = load_yaml("config.yaml")
    keywords = config["keywords"]
    locations = config["locations"]
    all_jobs = []

    # Scrape jobs from target firms with BeautifulSoup
    for firm, params in config["soup_targets"].items():
        jobs = scrape_job_listings(firm, params)
        jobs = filter_jobs(jobs, keywords, locations)
        all_jobs.extend(jobs)

    # Else call the API for target firms
    for firm, params in config["api_targets"].items():
        data = call_job_listing_api(params["url"], params["headers"])
        jobs = process_api_response(data, firm, params)
        jobs = filter_jobs(jobs, keywords, locations)
        all_jobs.extend(jobs)

    # Load previously identified jobs
    previous_jobs = load_jobs("jobs.json")
    new_jobs = identify_new_jobs(all_jobs, previous_jobs)

    # Send notification of new jobs
    if new_jobs:
        send_email_notification(new_jobs)

    # Save jobs
    previous_jobs.extend(new_jobs)
    save_jobs(previous_jobs, "jobs.json")

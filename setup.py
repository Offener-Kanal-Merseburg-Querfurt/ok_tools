from setuptools import find_packages
from setuptools import setup


setup(
    name='ok-tools',
    version='0.1',
    description='Tools to manage Offene Kanäle',
    long_description=(
        'Some tools to help the organisation of Offene Kanäle in Germany,'
        ' especially in Sachsen-Anhalt.'
    ),
    classifiers=[
        "Environment :: Web Environment",
        "Framework :: Django",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.10",
        "Operating System :: OS Independent",
    ],
    include_package_data=True,
    zip_safe=False,
    python_requires='>=3.10',
    packages=find_packages(
        '.',
        include=[
            'ok_tools',
            'registration',
            'licenses',
            'projects',
        ],
    ),
    install_requires=[
        'Django>=4.0.5',
        'PyPDF2!=2.10.1',
        'django-bootstrap-datepicker-plus',
        'django-crispy-forms',
        'django-revproxy>=0.10.0',
        'reportlab',
    ],
    extras_require={
        'test': [
            'pytest',
            'pytest-django',
            'zope.testbrowser',
        ],
    },
)
